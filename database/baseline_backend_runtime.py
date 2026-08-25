#!/usr/bin/env python3
"""Runtime support for migration-free Database Baseline v2 backends."""

from __future__ import annotations

from typing import Any, Mapping

from backend import DatabaseError, DatabaseMigrationError
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
    """Install the complete baseline once, or validate the installed checksum."""
    baseline = load_schema_baseline(backend.name)
    with backend.connect() as connection:
        try:
            marker = _marker(backend, connection)
            if marker is None:
                _execute_script(backend, connection, baseline.sql)
                _write_marker(
                    backend,
                    connection,
                    name=baseline.name,
                    checksum=baseline.checksum,
                )
                _commit(connection)
                installed_now = True
            else:
                installed_now = False
                if str(marker["name"]) != baseline.name:
                    raise DatabaseMigrationError(
                        f"unsupported database baseline: {marker['name']}"
                    )
                if str(marker["checksum"]) != baseline.checksum:
                    raise DatabaseMigrationError(
                        "installed Database Baseline v2 checksum does not match the current release"
                    )
            tables = _validate_structure(backend, connection)
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
        return {
            "schema_version": 2,
            "kind": "DatabaseStatus",
            "driver": backend.name,
            "connected": True,
            "initialized": initialized,
            "health": "ok" if initialized and checksum_matches and not missing else "error",
            "baseline": None if marker is None else str(marker["name"]),
            "baseline_checksum": None if marker is None else str(marker["checksum"]),
            "expected_baseline": BASELINE_NAME,
            "expected_checksum": baseline.checksum,
            "checksum_matches": checksum_matches,
            "missing_tables": missing,
        }


def validate_baseline(backend: Any) -> dict[str, Any]:
    """Validation alias used by legacy `migrate` and by health checks."""
    status = baseline_status(backend)
    valid = bool(
        status["initialized"]
        and status["checksum_matches"]
        and not status["missing_tables"]
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
