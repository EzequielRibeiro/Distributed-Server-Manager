#!/usr/bin/env python3
"""Runtime support for migration-free Database Baseline v2 backends."""

from __future__ import annotations

from typing import Any, Mapping

from backend import DatabaseError, DatabaseMigrationError
from baseline_upgrade_engine import (
    apply_pending_upgrades,
    seed_current_upgrades,
    upgrade_status,
)
from schema_baseline import BASELINE_NAME, baseline_marker_sql, load_schema_baseline

REQUIRED_TABLES = {
    "nodes",
    "controllers",
    "agents",
    "customers",
    "dashboard_users",
    "customer_account_members",
    "instances",
    "service_contracts",
    "schema_baseline",
}


def _execute_script(backend: Any, connection: Any, sql: str) -> None:
    name = backend.name
    if name == "sqlite":
        connection.executescript(sql)
        return
    if name == "postgresql":
        connection.execute(sql)
        return
    if name == "mysql":
        # Reuse only the proven statement parser/driver primitive. Migration
        # discovery and schema_migrations are intentionally bypassed.
        import mysql_engine

        mysql_engine._execute_script(connection, sql)
        return
    raise DatabaseError(f"unsupported baseline backend: {name}")


def _execute(backend: Any, connection: Any, sql: str, params=()):
    if backend.name == "mysql":
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql, params)
        return cursor
    return connection.execute(sql, params)


def _fetchone(backend: Any, result: Any):
    row = result.fetchone()
    try:
        result.close()
    except Exception:
        pass
    return row


def _table_names(backend: Any, connection: Any) -> set[str]:
    if backend.name == "postgresql":
        result = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        )
        rows = result.fetchall()
    elif backend.name == "mysql":
        result = _execute(
            backend,
            connection,
            "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",
        )
        rows = result.fetchall()
        result.close()
    else:
        rows = connection.execute(
            "SELECT name AS table_name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {str(row["table_name"]) for row in rows}


def _marker(backend: Any, connection: Any) -> Mapping[str, Any] | None:
    if "schema_baseline" not in _table_names(backend, connection):
        return None
    result = _execute(
        backend,
        connection,
        "SELECT name,checksum,installed_at FROM schema_baseline LIMIT 1",
    )
    return _fetchone(backend, result)


def _write_marker(backend: Any, connection: Any, *, name: str, checksum: str) -> None:
    _execute_script(backend, connection, baseline_marker_sql(backend.name) + ";")
    if backend.name == "postgresql":
        connection.execute("DELETE FROM schema_baseline")
        connection.execute(
            "INSERT INTO schema_baseline(singleton,name,checksum) VALUES (TRUE,%s,%s)",
            (name, checksum),
        )
    elif backend.name == "mysql":
        cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM schema_baseline")
            cursor.execute(
                "INSERT INTO schema_baseline(singleton,name,checksum) VALUES (1,%s,%s)",
                (name, checksum),
            )
        finally:
            cursor.close()
    else:
        connection.execute("DELETE FROM schema_baseline")
        connection.execute(
            "INSERT INTO schema_baseline(singleton,name,checksum) VALUES (1,?,?)",
            (name, checksum),
        )


def _commit(connection: Any) -> None:
    commit = getattr(connection, "commit", None)
    if callable(commit):
        commit()


def _rollback(connection: Any) -> None:
    rollback = getattr(connection, "rollback", None)
    if callable(rollback):
        try:
            rollback()
        except Exception:
            pass


def _validate_structure(backend: Any, connection: Any) -> list[str]:
    tables = _table_names(backend, connection)
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise DatabaseMigrationError(
            "incomplete Database Baseline v2; missing tables: " + ", ".join(missing)
        )
    return sorted(tables)


def initialize_baseline(backend: Any) -> dict[str, Any]:
    """Install Baseline v2 or advance an existing database through upgrades."""
    baseline = load_schema_baseline(backend.name)
    with backend.connect() as connection:
        try:
            marker = _marker(backend, connection)
            installed_now = False
            upgraded_now: list[int] = []

            if marker is None:
                _execute_script(backend, connection, baseline.sql)
                _write_marker(
                    backend,
                    connection,
                    name=baseline.name,
                    checksum=baseline.checksum,
                )
                # The consolidated current baseline already contains every
                # registered extension. Seed the ledger without replaying DDL.
                seed_current_upgrades(backend, connection)
                installed_now = True
                _commit(connection)
            else:
                if str(marker["name"]) != baseline.name:
                    raise DatabaseMigrationError(
                        f"unsupported database baseline: {marker['name']}"
                    )

                installed_checksum = str(marker["checksum"])
                if installed_checksum == baseline.checksum:
                    # Databases first installed before the ledger was
                    # introduced but already on this exact consolidated schema
                    # can safely adopt the current ledger state.
                    seed_current_upgrades(backend, connection)
                    _commit(connection)
                else:
                    # Once the ledger exists, this path is generic: future
                    # releases only append a BaselineUpgrade. Historical
                    # checksums are needed solely for the one-time pre-ledger
                    # compatibility bridge.
                    upgraded_now = apply_pending_upgrades(
                        backend,
                        connection,
                        installed_checksum=installed_checksum,
                    )
                    if not upgraded_now:
                        raise DatabaseMigrationError(
                            "Database Baseline v2 checksum differs but no registered upgrade is pending"
                        )
                    _validate_structure(backend, connection)
                    _write_marker(
                        backend,
                        connection,
                        name=baseline.name,
                        checksum=baseline.checksum,
                    )
                    _commit(connection)

            tables = _validate_structure(backend, connection)
            upgrades = upgrade_status(backend, connection)
            if upgrades["pending"]:
                raise DatabaseMigrationError(
                    "Database Baseline v2 has unapplied registered upgrades"
                )

            return {
                "schema_version": 2,
                "kind": "DatabaseStatus",
                "driver": backend.name,
                "connected": True,
                "initialized": True,
                "health": "ok",
                "baseline": baseline.name,
                "baseline_checksum": baseline.checksum,
                "installed_now": installed_now,
                "upgraded_now": upgraded_now,
                "upgrade_version": upgrades["current_version"],
                "upgrade_latest": upgrades["latest_version"],
                "tables": tables,
            }
        except Exception:
            _rollback(connection)
            raise


def baseline_status(backend: Any) -> dict[str, Any]:
    baseline = load_schema_baseline(backend.name)
    with backend.connect() as connection:
        marker = _marker(backend, connection)
        initialized = marker is not None
        checksum_matches = bool(
            marker
            and str(marker["name"]) == baseline.name
            and str(marker["checksum"]) == baseline.checksum
        )
        tables = _table_names(backend, connection)
        missing = sorted(REQUIRED_TABLES - tables) if initialized else sorted(REQUIRED_TABLES)

        try:
            upgrades = upgrade_status(backend, connection) if initialized else {
                "ledger_present": False,
                "current_version": 0,
                "latest_version": 0,
                "pending": [],
            }
            upgrade_error = None
        except DatabaseMigrationError as exc:
            upgrades = {
                "ledger_present": "baseline_upgrades" in tables,
                "current_version": 0,
                "latest_version": 0,
                "pending": [],
            }
            upgrade_error = str(exc)

        valid_upgrades = bool(
            upgrades["ledger_present"]
            and not upgrades["pending"]
            and upgrade_error is None
        )

        return {
            "schema_version": 2,
            "kind": "DatabaseStatus",
            "driver": backend.name,
            "connected": True,
            "initialized": initialized,
            "health": (
                "ok"
                if initialized and checksum_matches and not missing and valid_upgrades
                else "error"
            ),
            "baseline": None if marker is None else str(marker["name"]),
            "baseline_checksum": None if marker is None else str(marker["checksum"]),
            "expected_baseline": BASELINE_NAME,
            "expected_checksum": baseline.checksum,
            "checksum_matches": checksum_matches,
            "missing_tables": missing,
            "upgrade_ledger": upgrades["ledger_present"],
            "upgrade_version": upgrades["current_version"],
            "upgrade_latest": upgrades["latest_version"],
            "pending_upgrades": upgrades["pending"],
            "upgrade_error": upgrade_error,
        }


def validate_baseline(backend: Any) -> dict[str, Any]:
    """Validation alias used by legacy `migrate` and by health checks."""
    status = baseline_status(backend)
    valid = bool(
        status["initialized"]
        and status["checksum_matches"]
        and not status["missing_tables"]
        and status["upgrade_ledger"]
        and not status["pending_upgrades"]
        and status["upgrade_error"] is None
    )
    return {
        **status,
        "kind": "DatabaseCheck",
        "valid": valid,
    }


__all__ = [
    "REQUIRED_TABLES",
    "baseline_status",
    "initialize_baseline",
    "validate_baseline",
]
