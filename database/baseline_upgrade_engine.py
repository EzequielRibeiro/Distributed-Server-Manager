#!/usr/bin/env python3
"""Versioned post-baseline upgrades for Database Baseline v2.

New installations still receive one consolidated Baseline v2. Existing
installations use this small, append-only upgrade ledger whenever a later
release adds an additive schema extension to that baseline. This avoids
turning every historical baseline checksum into a special-case migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from activity_audit_schema import activity_audit_ddl
from agent_public_network_schema import ensure_agent_public_network_schema
from alert_event_action_schema import action_check_expression
from alert_scope_history_schema import alert_scope_history_ddl
from backend import DatabaseMigrationError
from discord_integration_schema import discord_integration_ddl


UpgradeApply = Callable[[Any, Any], None]


@dataclass(frozen=True)
class BaselineUpgrade:
    version: int
    name: str
    apply: UpgradeApply


DISCORD_TABLES = {
    "customer_discord_connections",
    "customer_discord_instance_bindings",
    "customer_discord_preferences",
    "customer_discord_oauth_states",
}

# Compatibility bridge for installations created before the upgrade ledger
# existed. Once a database has baseline_upgrades, future releases progress by
# version number and no longer need historical checksum entries.
LEGACY_BASELINE_START_VERSION = {
    "1c5fbc4a59b4b42326ccbeaa6701aaa269f4b3841e654f5b94f2c7a9b8eb3fab": 0,
}


def _execute_script(backend: Any, connection: Any, sql: str) -> None:
    if backend.name == "sqlite":
        connection.executescript(sql)
        return
    if backend.name == "postgresql":
        connection.execute(sql)
        return
    if backend.name == "mysql":
        import mysql_engine

        mysql_engine._execute_script(connection, sql)
        return
    raise DatabaseMigrationError(f"unsupported baseline backend: {backend.name}")


def _execute(backend: Any, connection: Any, sql: str, params=()):
    if backend.name == "mysql":
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql, params)
        return cursor
    return connection.execute(sql, params)


def _table_names(backend: Any, connection: Any) -> set[str]:
    if backend.name == "postgresql":
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ).fetchall()
    elif backend.name == "mysql":
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()"
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()
    else:
        rows = connection.execute(
            "SELECT name AS table_name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {str(row["table_name"]) for row in rows}


def _ledger_sql(backend_name: str) -> str:
    if backend_name == "postgresql":
        return """
CREATE TABLE IF NOT EXISTS baseline_upgrades (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
    if backend_name == "mysql":
        return """
CREATE TABLE IF NOT EXISTS baseline_upgrades (
    version INTEGER PRIMARY KEY,
    name VARCHAR(191) NOT NULL UNIQUE,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
    return """
CREATE TABLE IF NOT EXISTS baseline_upgrades (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _ensure_ledger(backend: Any, connection: Any) -> None:
    _execute_script(backend, connection, _ledger_sql(backend.name))


def _insert_ledger(backend: Any, connection: Any, upgrade: BaselineUpgrade) -> None:
    if backend.name == "mysql":
        cursor = connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO baseline_upgrades(version,name) VALUES (%s,%s)",
                (upgrade.version, upgrade.name),
            )
        finally:
            cursor.close()
    elif backend.name == "postgresql":
        connection.execute(
            "INSERT INTO baseline_upgrades(version,name) VALUES (%s,%s)",
            (upgrade.version, upgrade.name),
        )
    else:
        connection.execute(
            "INSERT INTO baseline_upgrades(version,name) VALUES (?,?)",
            (upgrade.version, upgrade.name),
        )


def _upgrade_discord(backend: Any, connection: Any) -> None:
    tables = _table_names(backend, connection)
    present = DISCORD_TABLES & tables
    if present and present != DISCORD_TABLES:
        missing = sorted(DISCORD_TABLES - present)
        raise DatabaseMigrationError(
            "partial Discord baseline upgrade; missing tables: " + ", ".join(missing)
        )
    if not present:
        _execute_script(backend, connection, discord_integration_ddl(backend.name))


def _upgrade_agent_public_network(backend: Any, connection: Any) -> None:
    if "agent_public_network_preconfiguration" in _table_names(backend, connection):
        return
    _execute_script(
        backend,
        connection,
        ensure_agent_public_network_schema("", backend.name),
    )


def _upgrade_activity_audit(backend: Any, connection: Any) -> None:
    if "activity_audit" in _table_names(backend, connection):
        return
    _execute_script(backend, connection, activity_audit_ddl(backend.name))


def _upgrade_resolved_alert_history_detach(backend: Any, connection: Any) -> None:
    ddl = alert_scope_history_ddl(backend.name)
    if ddl:
        _execute_script(backend, connection, ddl)


def _constraint_contains_note(backend: Any, connection: Any) -> bool:
    if backend.name == "postgresql":
        row = connection.execute(
            "SELECT pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint "
            "WHERE conrelid='public.alert_events'::regclass "
            "AND conname='alert_events_action_check'"
        ).fetchone()
        return bool(row and "NOTE" in str(row["definition"]).upper())
    if backend.name == "mysql":
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT CHECK_CLAUSE AS definition "
                "FROM information_schema.CHECK_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA=DATABASE() "
                "AND CONSTRAINT_NAME='chk_alert_events_action'"
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
        return bool(row and "NOTE" in str(row["definition"]).upper())
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='alert_events'"
    ).fetchone()
    return bool(row and "NOTE" in str(row["sql"]).upper())


def _mysql_is_mariadb(connection: Any) -> bool:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT VERSION() AS version")
        row = cursor.fetchone()
    finally:
        cursor.close()
    return bool(row and "mariadb" in str(row["version"]).lower())


def _upgrade_alert_events_note_sqlite(connection: Any) -> None:
    if "alert_events__note_upgrade_new" in {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }:
        raise DatabaseMigrationError(
            "stale alert_events__note_upgrade_new table blocks NOTE action upgrade"
        )

    objects = connection.execute(
        "SELECT type,name,sql FROM sqlite_master "
        "WHERE tbl_name='alert_events' "
        "AND type IN ('index','trigger') "
        "AND sql IS NOT NULL ORDER BY type,name"
    ).fetchall()

    connection.execute(
        """
CREATE TABLE alert_events__note_upgrade_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (
        action IN ('OPEN','REOPEN','ESCALATE','ACK','RESOLVE','SUPPRESS','NOTE')
    ),
    level TEXT NOT NULL CHECK (level IN ('INFO','WARNING','CRITICAL')),
    old_state TEXT,
    new_state TEXT NOT NULL CHECK (
        new_state IN ('OPEN','ACKNOWLEDGED','RESOLVED','SUPPRESSED')
    ),
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE
)
"""
    )
    connection.execute(
        "INSERT INTO alert_events__note_upgrade_new("
        "id,alert_id,action,level,old_state,new_state,message,created_at"
        ") SELECT id,alert_id,action,level,old_state,new_state,message,created_at "
        "FROM alert_events"
    )
    connection.execute("DROP TABLE alert_events")
    connection.execute(
        "ALTER TABLE alert_events__note_upgrade_new RENAME TO alert_events"
    )
    for row in objects:
        connection.execute(str(row["sql"]))


def _upgrade_alert_events_note_action(backend: Any, connection: Any) -> None:
    if "alert_events" not in _table_names(backend, connection):
        raise DatabaseMigrationError("alert_events table is missing")
    if _constraint_contains_note(backend, connection):
        return

    expression = action_check_expression()
    if backend.name == "postgresql":
        connection.execute(
            "ALTER TABLE public.alert_events "
            "DROP CONSTRAINT IF EXISTS alert_events_action_check"
        )
        connection.execute(
            "ALTER TABLE public.alert_events "
            "ADD CONSTRAINT alert_events_action_check CHECK (" + expression + ")"
        )
        return

    if backend.name == "mysql":
        cursor = connection.cursor()
        try:
            if _mysql_is_mariadb(connection):
                cursor.execute(
                    "ALTER TABLE alert_events DROP CONSTRAINT chk_alert_events_action"
                )
            else:
                cursor.execute(
                    "ALTER TABLE alert_events DROP CHECK chk_alert_events_action"
                )
            cursor.execute(
                "ALTER TABLE alert_events "
                "ADD CONSTRAINT chk_alert_events_action CHECK (" + expression + ")"
            )
        finally:
            cursor.close()
        return

    if backend.name == "sqlite":
        _upgrade_alert_events_note_sqlite(connection)
        return

    raise DatabaseMigrationError(f"unsupported baseline backend: {backend.name}")


UPGRADES = (
    BaselineUpgrade(1, "discord_integration", _upgrade_discord),
    BaselineUpgrade(2, "agent_public_network", _upgrade_agent_public_network),
    BaselineUpgrade(3, "activity_audit", _upgrade_activity_audit),
    BaselineUpgrade(4, "resolved_alert_history_detach", _upgrade_resolved_alert_history_detach),
    BaselineUpgrade(5, "alert_events_note_action", _upgrade_alert_events_note_action),
)


def latest_upgrade_version() -> int:
    return UPGRADES[-1].version if UPGRADES else 0


def _read_applied(backend: Any, connection: Any) -> dict[int, str]:
    if "baseline_upgrades" not in _table_names(backend, connection):
        return {}
    result = _execute(
        backend,
        connection,
        "SELECT version,name FROM baseline_upgrades ORDER BY version",
    )
    try:
        rows = result.fetchall()
    finally:
        try:
            result.close()
        except Exception:
            pass
    return {int(row["version"]): str(row["name"]) for row in rows}


def _validate_ledger(applied: Mapping[int, str]) -> None:
    registered = {upgrade.version: upgrade.name for upgrade in UPGRADES}
    for version, name in applied.items():
        expected = registered.get(version)
        if expected is None:
            raise DatabaseMigrationError(
                f"database contains unknown Baseline v2 upgrade version: {version}"
            )
        if expected != name:
            raise DatabaseMigrationError(
                f"Baseline v2 upgrade {version} name mismatch: {name} != {expected}"
            )
    if applied:
        maximum = max(applied)
        missing = [version for version in range(1, maximum + 1) if version not in applied]
        if missing:
            raise DatabaseMigrationError(
                "non-contiguous Baseline v2 upgrade ledger; missing versions: "
                + ", ".join(map(str, missing))
            )


def seed_current_upgrades(backend: Any, connection: Any) -> None:
    """Reconcile and record extensions already represented by the current baseline.

    Exact-checksum databases may predate the upgrade ledger or may have been
    partially materialized by an older release. Every registered upgrade is
    therefore idempotently reconciled before its ledger entry is recorded.
    """
    _ensure_ledger(backend, connection)
    applied = _read_applied(backend, connection)
    _validate_ledger(applied)
    for upgrade in UPGRADES:
        if upgrade.version not in applied:
            upgrade.apply(backend, connection)
            _insert_ledger(backend, connection, upgrade)


def upgrade_status(backend: Any, connection: Any) -> dict[str, Any]:
    tables = _table_names(backend, connection)
    ledger_present = "baseline_upgrades" in tables
    applied = _read_applied(backend, connection) if ledger_present else {}
    _validate_ledger(applied)
    pending = [
        {"version": upgrade.version, "name": upgrade.name}
        for upgrade in UPGRADES
        if upgrade.version not in applied
    ]
    return {
        "ledger_present": ledger_present,
        "current_version": max(applied, default=0),
        "latest_version": latest_upgrade_version(),
        "pending": pending,
    }


def apply_pending_upgrades(
    backend: Any,
    connection: Any,
    *,
    installed_checksum: str,
) -> list[int]:
    """Apply pending registered upgrades and return versions applied now.

    Databases with a ledger advance solely by the ledger. Pre-ledger databases
    are admitted only through the finite compatibility bridge above; after this
    first reconciliation they become ordinary versioned-upgrade databases.
    """
    tables = _table_names(backend, connection)
    ledger_present = "baseline_upgrades" in tables

    if ledger_present:
        applied = _read_applied(backend, connection)
        _validate_ledger(applied)
    else:
        start_version = LEGACY_BASELINE_START_VERSION.get(installed_checksum)
        if start_version is None:
            raise DatabaseMigrationError(
                "pre-upgrade-ledger Database Baseline v2 checksum is not recognized; "
                "refusing an unsafe automatic upgrade"
            )
        _ensure_ledger(backend, connection)
        applied = {}
        for upgrade in UPGRADES:
            if upgrade.version <= start_version:
                _insert_ledger(backend, connection, upgrade)
                applied[upgrade.version] = upgrade.name

    completed: list[int] = []
    for upgrade in UPGRADES:
        if upgrade.version in applied:
            continue
        upgrade.apply(backend, connection)
        _insert_ledger(backend, connection, upgrade)
        applied[upgrade.version] = upgrade.name
        completed.append(upgrade.version)

    _validate_ledger(applied)
    return completed


__all__ = [
    "UPGRADES",
    "apply_pending_upgrades",
    "latest_upgrade_version",
    "seed_current_upgrades",
    "upgrade_status",
]
