#!/usr/bin/env python3
"""PostgreSQL persistence and migration engine for Capivara DSM."""

from __future__ import annotations

import hashlib
import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend import (
    DatabaseConfig,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseMigrationError,
)


MIGRATION_PATTERN = re.compile(
    r"^(?P<version>[0-9]{3})_(?P<name>[a-z0-9_]+)\.sql$"
)

POSTGRESQL_SSLMODE_ALIASES = {
    "preferred": "prefer",
    "required": "require",
}

POSTGRESQL_SSLMODES = {
    "disable",
    "allow",
    "prefer",
    "require",
    "verify-ca",
    "verify-full",
}

SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CONSOLIDATED_SCHEMA_VERSION = 41
CONSOLIDATED_SCHEMA_NAME = "consolidated_schema"
REQUIRED_SCHEMA_TABLES = {
    "agents", "controllers", "agent_pairing_tokens", "agent_credentials",
    "agent_runtime_inventory", "schema_migrations",
}


def consolidated_schema_path() -> Path:
    return Path(__file__).resolve().parent / "schemas" / "postgresql.sql"


def apply_consolidated_schema(connection: Any) -> list[int]:
    path = consolidated_schema_path()
    if not path.is_file():
        raise DatabaseMigrationError(f"consolidated PostgreSQL schema not found: {path}")
    sql = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    try:
        with connection.transaction():
            connection.execute(sql)
            connection.execute(SCHEMA_MIGRATIONS_SQL)
            connection.execute(
                "INSERT INTO schema_migrations(version,name,checksum) VALUES (%s,%s,%s)",
                (CONSOLIDATED_SCHEMA_VERSION, CONSOLIDATED_SCHEMA_NAME, checksum),
            )
    except Exception as exc:
        raise DatabaseMigrationError(f"consolidated PostgreSQL schema failed: {exc}") from exc
    return [CONSOLIDATED_SCHEMA_VERSION]


def validate_schema(connection: Any) -> None:
    rows = connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    ).fetchall()
    names = {str(row["table_name"]) for row in rows}
    missing = sorted(REQUIRED_SCHEMA_TABLES - names)
    if missing:
        raise DatabaseMigrationError("incomplete PostgreSQL schema; missing: " + ", ".join(missing))


@dataclass(frozen=True)
class Migration:
    """One versioned PostgreSQL migration."""

    version: int
    name: str
    path: Path
    sql: str
    checksum: str


def migration_directory() -> Path:
    """Return the consolidated PostgreSQL schema directory."""

    return consolidated_schema_path().parent


def load_migrations(
    directory: Path | None = None,
) -> list[Migration]:
    """Load PostgreSQL migrations in version order."""

    if directory is None:
        path = consolidated_schema_path()
        sql = path.read_text(encoding="utf-8")
        return [Migration(
            version=CONSOLIDATED_SCHEMA_VERSION,
            name=CONSOLIDATED_SCHEMA_NAME,
            path=path,
            sql=sql,
            checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        )]

    if not directory.is_dir():
        raise DatabaseConfigurationError(
            "PostgreSQL migration directory "
            f"not found: {directory}"
        )

    migrations: list[Migration] = []
    seen_versions: set[int] = set()

    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_PATTERN.fullmatch(path.name)

        if not match:
            raise DatabaseConfigurationError(
                "invalid PostgreSQL migration "
                f"filename: {path.name}"
            )

        version = int(match.group("version"))

        if version in seen_versions:
            raise DatabaseConfigurationError(
                "duplicate PostgreSQL migration "
                f"version: {version}"
            )

        seen_versions.add(version)

        sql = path.read_text(encoding="utf-8")

        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
                sql=sql,
                checksum=hashlib.sha256(
                    sql.encode("utf-8")
                ).hexdigest(),
            )
        )

    if not migrations:
        raise DatabaseConfigurationError(
            "no PostgreSQL migrations were found"
        )

    return migrations


def normalize_sslmode(value: str) -> str:
    """Return a PostgreSQL/libpq compatible sslmode."""

    if not isinstance(value, str):
        raise DatabaseConfigurationError(
            "PostgreSQL TLS mode must be a string"
        )

    mode = value.strip().lower()

    if not mode:
        mode = "prefer"

    mode = POSTGRESQL_SSLMODE_ALIASES.get(
        mode,
        mode,
    )

    if mode not in POSTGRESQL_SSLMODES:
        raise DatabaseConfigurationError(
            "unsupported PostgreSQL TLS mode: "
            f"{value}"
        )

    return mode


def read_password_file(
    path: str | None,
) -> str | None:
    """Read database password from a dedicated file."""

    if not path:
        return None

    password_path = (
        Path(path)
        .expanduser()
        .resolve()
    )

    if not password_path.is_file():
        raise DatabaseConfigurationError(
            "database password file not found: "
            f"{password_path}"
        )

    try:
        value = password_path.read_text(
            encoding="utf-8"
        )

    except OSError as exc:
        raise DatabaseConfigurationError(
            "could not read database password "
            f"file: {password_path}: {exc}"
        ) from exc

    password = value.rstrip("\r\n")

    if not password:
        raise DatabaseConfigurationError(
            "database password file is empty"
        )

    if "\n" in password or "\r" in password:
        raise DatabaseConfigurationError(
            "database password file must "
            "contain exactly one line"
        )

    return password


def validate_config(
    config: DatabaseConfig,
) -> None:
    """Validate PostgreSQL-specific configuration."""

    driver = config.driver.strip().lower()

    if driver not in {
        "postgresql",
        "postgres",
        "pgsql",
    }:
        raise DatabaseConfigurationError(
            "PostgreSQL engine cannot use "
            f"driver: {config.driver}"
        )

    if not config.database.strip():
        raise DatabaseConfigurationError(
            "PostgreSQL database name is required"
        )

    if not config.host or not config.host.strip():
        raise DatabaseConfigurationError(
            "PostgreSQL host is required"
        )

    if not config.user or not config.user.strip():
        raise DatabaseConfigurationError(
            "PostgreSQL user is required"
        )

    if config.port is None:
        raise DatabaseConfigurationError(
            "PostgreSQL port is required"
        )

    if not 1 <= config.port <= 65535:
        raise DatabaseConfigurationError(
            "PostgreSQL port must be between "
            "1 and 65535"
        )

    if config.connect_timeout <= 0:
        raise DatabaseConfigurationError(
            "PostgreSQL connect timeout must "
            "be greater than zero"
        )

    normalize_sslmode(config.tls_mode)


def connection_parameters(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Build Psycopg connection parameters."""

    validate_config(config)

    password = read_password_file(
        config.password_file
    )

    parameters: dict[str, Any] = {
        "host": config.host.strip(),
        "port": config.port,
        "dbname": config.database.strip(),
        "user": config.user.strip(),
        "connect_timeout": config.connect_timeout,
        "sslmode": normalize_sslmode(
            config.tls_mode
        ),
    }

    if password is not None:
        parameters["password"] = password

    return parameters


def _load_psycopg():
    """Load Psycopg lazily."""

    try:
        psycopg = importlib.import_module(
            "psycopg"
        )

        rows = importlib.import_module(
            "psycopg.rows"
        )

    except (
        ImportError,
        ModuleNotFoundError,
    ) as exc:
        raise DatabaseConfigurationError(
            "PostgreSQL support requires "
            "Psycopg 3. Install the optional "
            "PostgreSQL database dependency."
        ) from exc

    dict_row = getattr(
        rows,
        "dict_row",
        None,
    )

    if dict_row is None:
        raise DatabaseConfigurationError(
            "installed Psycopg does not expose "
            "psycopg.rows.dict_row"
        )

    return psycopg, dict_row


def connect(
    config: DatabaseConfig,
):
    """Open a PostgreSQL connection."""

    parameters = connection_parameters(
        config
    )

    psycopg, dict_row = _load_psycopg()

    try:
        return psycopg.connect(
            **parameters,
            row_factory=dict_row,
        )

    except Exception as exc:
        raise DatabaseConnectionError(
            "could not connect to PostgreSQL: "
            f"{exc}"
        ) from exc

def _serialize_value(
    value: Any,
) -> Any:
    """Normalize PostgreSQL values for backend JSON payloads."""

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return value


def _serialize_row(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a JSON-safe PostgreSQL result row."""

    return {
        key: _serialize_value(value)
        for key, value in row.items()
    }

def applied_migrations(
    connection: Any,
) -> dict[int, dict[str, Any]]:
    """Return migrations recorded by PostgreSQL."""

    try:
        with connection.transaction():
            connection.execute(
                SCHEMA_MIGRATIONS_SQL
            )

            rows = connection.execute(
                """
                SELECT
                    version,
                    name,
                    checksum,
                    applied_at
                FROM schema_migrations
                ORDER BY version
                """
            ).fetchall()

    except Exception as exc:
        raise DatabaseMigrationError(
            "could not read PostgreSQL "
            f"migration state: {exc}"
        ) from exc

    return {
        int(row["version"]): _serialize_row(row)
        for row in rows
    }


def apply_migrations(
    connection: Any,
    migrations: Iterable[Migration] | None = None,
) -> list[int]:
    """Apply pending PostgreSQL migrations atomically."""

    migration_list = list(
        migrations or load_migrations()
    )

    applied = applied_migrations(
        connection
    )

    completed: list[int] = []

    for migration in migration_list:
        previous = applied.get(
            migration.version
        )

        if previous:
            if previous["checksum"] != migration.checksum:
                raise DatabaseMigrationError(
                    "applied PostgreSQL migration "
                    f"{migration.version:03d} "
                    "checksum does not match"
                )

            continue

        try:
            with connection.transaction():
                connection.execute(
                    migration.sql
                )

                connection.execute(
                    """
                    INSERT INTO schema_migrations(
                        version,
                        name,
                        checksum
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (
                        migration.version,
                        migration.name,
                        migration.checksum,
                    ),
                )

        except Exception as exc:
            raise DatabaseMigrationError(
                "PostgreSQL migration "
                f"{migration.version:03d}_"
                f"{migration.name} failed: {exc}"
            ) from exc

        completed.append(
            migration.version
        )

        applied[migration.version] = {
            "version": migration.version,
            "name": migration.name,
            "checksum": migration.checksum,
            "applied_at": None,
        }

    return completed


def _schema_migrations_exists(
    connection: Any,
) -> bool:
    """Return whether migration tracking exists."""

    row = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = 'schema_migrations'
        ) AS exists
        """
    ).fetchone()

    return bool(
        row
        and row.get("exists", False)
    )


def _database_status_connection(
    connection: Any,
    config: DatabaseConfig,
    *,
    applied_now: Iterable[int] = (),
) -> dict[str, Any]:
    """Build status using an existing connection."""

    try:
        with connection.transaction():
            server = connection.execute(
                """
                SELECT
                    current_database() AS database,
                    current_user AS user,
                    current_setting(
                        'server_version'
                    ) AS server_version
                """
            ).fetchone()

            initialized = (
                _schema_migrations_exists(
                    connection
                )
            )

            migrations: list[
                dict[str, Any]
            ] = []

            if initialized:
                rows = connection.execute(
                    """
                    SELECT
                        version,
                        name,
                        checksum,
                        applied_at
                    FROM schema_migrations
                    ORDER BY version
                    """
                ).fetchall()

                migrations = [
                    _serialize_row(row)
                    for row in rows
                ]

    except Exception as exc:
        raise DatabaseConnectionError(
            "could not read PostgreSQL "
            f"status: {exc}"
        ) from exc

    current_migration = (
        int(migrations[-1]["version"])
        if migrations
        else 0
    )

    return {
        "schema_version": 1,
        "kind": "DatabaseStatus",
        "driver": "postgresql",
        "database": (
            server.get("database")
            if server
            else config.database
        ),
        "user": (
            server.get("user")
            if server
            else config.user
        ),
        "server_version": (
            server.get("server_version")
            if server
            else None
        ),
        "connected": True,
        "initialized": initialized,
        "health": "ok",
        "current_migration": current_migration,
        "applied_migrations": migrations,
        "applied_now": list(applied_now),
    }


def database_status(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Return PostgreSQL schema and migration status."""

    connection = connect(config)

    try:
        return _database_status_connection(
            connection,
            config,
        )

    finally:
        connection.close()


def check_database(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Run PostgreSQL connectivity/health checks."""

    connection = connect(config)

    try:
        with connection.transaction():
            row = connection.execute(
                """
                SELECT
                    1 AS ok,
                    current_database() AS database,
                    current_user AS user
                """
            ).fetchone()

        valid = bool(
            row
            and row.get("ok") == 1
        )

        return {
            "schema_version": 1,
            "kind": "DatabaseCheck",
            "driver": "postgresql",
            "database": (
                row.get("database")
                if row
                else config.database
            ),
            "user": (
                row.get("user")
                if row
                else config.user
            ),
            "connected": True,
            "health": (
                "ok"
                if valid
                else "error"
            ),
            "valid": valid,
        }

    except DatabaseConnectionError:
        raise

    except Exception as exc:
        raise DatabaseConnectionError(
            "PostgreSQL health check failed: "
            f"{exc}"
        ) from exc

    finally:
        connection.close()


def initialize(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Initialize PostgreSQL and apply pending migrations."""

    connection = connect(config)

    try:
        initialized = _schema_migrations_exists(connection)
        # Psycopg starts an implicit transaction even for the detection SELECT.
        # Commit it before opening the schema transaction; otherwise
        # connection.transaction() becomes a savepoint and closing the outer
        # connection silently rolls the complete schema back.
        connection.commit()
        completed = ([] if initialized else apply_consolidated_schema(connection))
        validate_schema(connection)
        result = _database_status_connection(
            connection,
            config,
            applied_now=completed,
        )
        connection.commit()
        return result

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def migrate(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Apply pending PostgreSQL migrations."""

    return initialize(config)
