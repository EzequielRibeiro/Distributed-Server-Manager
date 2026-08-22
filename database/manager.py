#!/usr/bin/env python3
"""Capivara DSM database manager and compatibility facade."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable


DATABASE_DIR = Path(__file__).resolve().parent

if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))


import sqlite_engine

from backend import (
    DatabaseError as BackendDatabaseError,
    DatabaseConfig,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseMigrationError,
)

from backend_factory import (
    create_backend,
    normalize_database_driver,
)

# =============================================================
# SQLite compatibility API
#
# Existing Capivara modules still import database/manager.py
# directly. Keep this API stable while consumers are migrated
# gradually to DatabaseBackend.
# =============================================================

DatabaseError = sqlite_engine.DatabaseError
Migration = sqlite_engine.Migration


def default_root() -> Path:
    """Return the configured Capivara root directory."""

    return sqlite_engine.default_root()


def default_database(
    root: Path,
) -> Path:
    """Return the legacy/default SQLite database path."""

    return sqlite_engine.default_database(root)


def migration_directory() -> Path:
    """Return the current SQLite migration directory."""

    return sqlite_engine.migration_directory()


def load_migrations(
    directory: Path | None = None,
) -> list[Migration]:
    """Load SQLite migrations using the legacy API."""

    return sqlite_engine.load_migrations(
        directory
    )


def connect(
    database: Path,
    *,
    create_parent: bool = True,
) -> sqlite3.Connection:
    """Open a legacy SQLite connection.

    New database-aware code should prefer DatabaseBackend.
    """

    return sqlite_engine.connect(
        database,
        create_parent=create_parent,
    )


def applied_migrations(
    connection: sqlite3.Connection,
) -> dict[int, sqlite3.Row]:
    """Return migrations recorded by SQLite."""

    return sqlite_engine.applied_migrations(
        connection
    )


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Iterable[Migration] | None = None,
) -> list[int]:
    """Apply SQLite migrations using the legacy API."""

    return sqlite_engine.apply_migrations(
        connection,
        migrations,
    )


def initialize(
    database: Path,
) -> dict[str, object]:
    """Initialize SQLite using the legacy API."""

    return sqlite_engine.initialize(
        database
    )


def database_status(
    database: Path,
    *,
    applied_now: Iterable[int] = (),
) -> dict[str, object]:
    """Return SQLite status using the legacy API."""

    return sqlite_engine.database_status(
        database,
        applied_now=applied_now,
    )


def check_database(
    database: Path,
) -> dict[str, object]:
    """Run legacy SQLite database checks."""

    return sqlite_engine.check_database(
        database
    )


def backup_database(
    database: Path,
    destination: Path,
) -> dict[str, object]:
    """Create a legacy SQLite backup."""

    return sqlite_engine.backup_database(
        database,
        destination,
    )


# =============================================================
# Multi-backend configuration
# =============================================================

def default_driver() -> str:
    """Return the configured database driver."""

    return normalize_database_driver(
        os.environ.get(
            "DSM_DATABASE_DRIVER",
            "sqlite",
        )
    )


def _environment_port(
    default: int,
) -> int:
    """Read and validate DSM_DATABASE_PORT."""

    value = os.environ.get(
        "DSM_DATABASE_PORT"
    )

    if not value:
        return default

    try:
        port = int(value)

    except ValueError as exc:
        raise DatabaseConfigurationError(
            "DSM_DATABASE_PORT must be an integer"
        ) from exc

    if not 1 <= port <= 65535:
        raise DatabaseConfigurationError(
            "DSM_DATABASE_PORT must be between "
            "1 and 65535"
        )

    return port


def _validate_port(
    port: int,
) -> int:
    """Validate a network database port."""

    if not 1 <= port <= 65535:
        raise DatabaseConfigurationError(
            "database port must be between "
            "1 and 65535"
        )

    return port


def _validate_connect_timeout(
    timeout: int,
) -> int:
    """Validate database connection timeout."""

    if timeout <= 0:
        raise DatabaseConfigurationError(
            "database connect timeout must "
            "be greater than zero"
        )

    return timeout


def config_from_args(
    args: argparse.Namespace,
) -> DatabaseConfig:
    """Build backend-independent database configuration."""

    driver = normalize_database_driver(
        args.driver
    )

    connect_timeout = (
        _validate_connect_timeout(
            args.connect_timeout
        )
    )

    root = args.root.resolve()

    # ---------------------------------------------------------
    # SQLite
    # ---------------------------------------------------------

    if driver == "sqlite":
        database = (
            args.database.resolve()
            if args.database
            else default_database(root)
        )

        return DatabaseConfig(
            driver="sqlite",
            database=str(database),
            connect_timeout=connect_timeout,
        )

    # ---------------------------------------------------------
    # PostgreSQL / MySQL
    # ---------------------------------------------------------

    database_name = (
        args.database_name
        or os.environ.get(
            "DSM_DATABASE_NAME",
            "capivara",
        )
    )

    host = (
        args.host
        or os.environ.get(
            "DSM_DATABASE_HOST",
            ""
        )
    ).strip()

    user = (
        args.user
        or os.environ.get(
            "DSM_DATABASE_USER",
            ""
        )
    ).strip()

    password_file = (
        args.password_file
        or os.environ.get(
            "DSM_DATABASE_PASSWORD_FILE"
        )
    )

    tls_mode = (
        args.tls
        or os.environ.get(
            "DSM_DATABASE_TLS",
            "preferred",
        )
    ).strip().lower()

    if not database_name:
        raise DatabaseConfigurationError(
            f"{driver} requires a database name"
        )

    if not host:
        raise DatabaseConfigurationError(
            f"{driver} requires a database host"
        )

    if not user:
        raise DatabaseConfigurationError(
            f"{driver} requires a database user"
        )

    if driver == "postgresql":
        port = (
            args.port
            if args.port is not None
            else _environment_port(5432)
        )

    else:
        port = (
            args.port
            if args.port is not None
            else _environment_port(3306)
        )

    port = _validate_port(port)

    return DatabaseConfig(
        driver=driver,
        database=database_name,
        host=host,
        port=port,
        user=user,
        password_file=password_file,
        tls_mode=tls_mode,
        connect_timeout=connect_timeout,
    )


# =============================================================
# CLI
# =============================================================

def build_parser() -> argparse.ArgumentParser:
    """Build database management CLI parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Capivara DSM database manager"
        )
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=default_root(),
    )

    parser.add_argument(
        "--driver",
        default=default_driver(),
        help=(
            "database driver: "
            "sqlite, postgresql or mysql"
        ),
    )

    # Legacy SQLite path option.
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite database path",
    )

    # Network database options.
    parser.add_argument(
        "--database-name",
        help=(
            "PostgreSQL/MySQL database name"
        ),
    )

    parser.add_argument(
        "--host",
        help="database server hostname",
    )

    parser.add_argument(
        "--port",
        type=int,
        help="database server port",
    )

    parser.add_argument(
        "--user",
        help="database user",
    )

    parser.add_argument(
        "--password-file",
        help=(
            "file containing the database password"
        ),
    )

    parser.add_argument(
        "--tls",
        help=(
            "database TLS mode"
        ),
    )

    try:
        default_timeout = int(
            os.environ.get(
                "DSM_DATABASE_CONNECT_TIMEOUT",
                "5",
            )
        )

    except ValueError as exc:
        raise DatabaseConfigurationError(
            "DSM_DATABASE_CONNECT_TIMEOUT "
            "must be an integer"
        ) from exc

    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=default_timeout,
        help="database connection timeout",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser(
        "init",
        help=(
            "create/initialize database "
            "from the consolidated schema"
        ),
    )

    subparsers.add_parser(
        "migrate",
        help="validate/apply the consolidated schema idempotently",
    )

    subparsers.add_parser(
        "status",
        help=(
            "show consolidated schema and database status"
        ),
    )

    subparsers.add_parser(
        "check",
        help="run database health checks",
    )

    backup_parser = (
        subparsers.add_parser(
            "backup",
            help="create a consistent database backup",
        )
    )

    backup_parser.add_argument(
        "destination",
        help=(
            "backend-specific backup destination"
        ),
    )

    restore_parser = subparsers.add_parser(
        "restore",
        help="restore a backend-specific backup",
    )
    restore_parser.add_argument("source")
    restore_parser.add_argument(
        "--confirm-restore",
        action="store_true",
        help="confirm replacement of the configured database",
    )

    return parser


def execute_backend_command(
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Execute a CLI command through DatabaseBackend."""

    config = config_from_args(
        args
    )

    backend = create_backend(
        config
    )

    try:
        if args.command == "init":
            return dict(
                backend.initialize()
            )

        if args.command == "migrate":
            return dict(
                backend.migrate()
            )

        if args.command == "status":
            return dict(
                backend.status()
            )

        if args.command == "check":
            return dict(
                backend.health_check()
            )

        if args.command == "backup":
            return dict(
                backend.backup(
                    args.destination
                )
            )

        if args.command == "restore":
            if not args.confirm_restore:
                raise DatabaseConfigurationError(
                    "restore requires --confirm-restore"
                )
            return dict(backend.restore(args.source))

        raise DatabaseConfigurationError(
            "unsupported database command: "
            f"{args.command}"
        )

    finally:
        backend.close()


def _error_payload(
    exc: Exception,
) -> dict[str, object]:
    """Build stable database CLI error output."""

    return {
        "schema_version": 1,
        "kind": "DatabaseError",
        "error": str(exc),
    }


def main(
    argv: list[str] | None = None,
) -> int:
    """Run the Capivara database manager CLI."""

    try:
        parser = build_parser()

        args = parser.parse_args(
            argv
        )

        payload = execute_backend_command(
            args
        )

    except (
        DatabaseError,
        BackendDatabaseError,
        DatabaseConfigurationError,
        DatabaseConnectionError,
        DatabaseMigrationError,
        sqlite3.Error,
        OSError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                _error_payload(exc),
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )

        return 1

    print(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
    )

    if (
        args.command == "check"
        and not payload.get("valid", False)
    ):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
