#!/usr/bin/env python3
"""MySQL/MariaDB persistence primitives for Capivara DSM."""

from __future__ import annotations

import hashlib
import importlib
import os
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


MYSQL_TLS_MODE_ALIASES = {
    "prefer": "preferred",
    "require": "required",
    "verify_ca": "verify-ca",
    "verify_identity": "verify-full",
}


MYSQL_TLS_MODES = {
    "disable",
    "preferred",
    "required",
    "verify-ca",
    "verify-full",
}

CONSOLIDATED_SCHEMA_VERSION = 41
CONSOLIDATED_SCHEMA_NAME = "consolidated_schema"
REQUIRED_SCHEMA_TABLES = {
    "agents", "controllers", "agent_pairing_tokens", "agent_credentials",
    "agent_runtime_inventory", "schema_migrations",
}


def consolidated_schema_path(driver: str = "mysql") -> Path:
    backend = "mariadb" if driver.strip().lower() == "mariadb" else "mysql"
    return Path(__file__).resolve().parent / "schemas" / f"{backend}.sql"


def apply_consolidated_schema(connection: Any, driver: str = "mysql") -> list[int]:
    path = consolidated_schema_path(driver)
    if not path.is_file():
        raise DatabaseMigrationError(f"consolidated MySQL schema not found: {path}")
    sql = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    try:
        _execute_script(connection, sql)
        cursor = connection.cursor()
        try:
            cursor.execute(SCHEMA_MIGRATIONS_SQL)
            cursor.execute(
                "INSERT INTO schema_migrations(version,name,checksum) VALUES (%s,%s,%s)",
                (CONSOLIDATED_SCHEMA_VERSION, CONSOLIDATED_SCHEMA_NAME, checksum),
            )
        finally:
            cursor.close()
        connection.commit()
    except Exception as exc:
        try:
            connection.rollback()
        except Exception:
            pass
        raise DatabaseMigrationError(f"consolidated MySQL schema failed: {exc}") from exc
    return [CONSOLIDATED_SCHEMA_VERSION]


def validate_schema(connection: Any) -> None:
    cursor = _dictionary_cursor(connection)
    try:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()")
        names = {str(row["table_name"]) for row in cursor.fetchall()}
    finally:
        cursor.close()
    missing = sorted(REQUIRED_SCHEMA_TABLES - names)
    if missing:
        raise DatabaseMigrationError("incomplete MySQL/MariaDB schema; missing: " + ", ".join(missing))


@dataclass(frozen=True)
class Migration:
    """One versioned MySQL/MariaDB migration."""

    version: int
    name: str
    path: Path
    sql: str
    checksum: str


def migration_directory() -> Path:
    """Return the consolidated MySQL schema directory."""

    return consolidated_schema_path().parent


def load_migrations(
    directory: Path | None = None,
) -> list[Migration]:
    """Load MySQL/MariaDB migrations in version order."""

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
            "MySQL migration directory "
            f"not found: {directory}"
        )

    migrations: list[Migration] = []
    seen_versions: set[int] = set()

    for path in sorted(
        directory.glob("*.sql")
    ):
        match = MIGRATION_PATTERN.fullmatch(
            path.name
        )

        if not match:
            raise DatabaseConfigurationError(
                "invalid MySQL migration "
                f"filename: {path.name}"
            )

        version = int(
            match.group("version")
        )

        if version in seen_versions:
            raise DatabaseConfigurationError(
                "duplicate MySQL migration "
                f"version: {version}"
            )

        seen_versions.add(version)

        sql = path.read_text(
            encoding="utf-8"
        )

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
            "no MySQL migrations were found"
        )

    return migrations


def normalize_tls_mode(
    value: str,
) -> str:
    """Return the canonical Capivara MySQL TLS mode."""

    if not isinstance(value, str):
        raise DatabaseConfigurationError(
            "MySQL TLS mode must be a string"
        )

    mode = value.strip().lower()

    if not mode:
        mode = "preferred"

    mode = MYSQL_TLS_MODE_ALIASES.get(
        mode,
        mode,
    )

    if mode not in MYSQL_TLS_MODES:
        raise DatabaseConfigurationError(
            "unsupported MySQL TLS mode: "
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

    password = value.rstrip(
        "\r\n"
    )

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
    """Validate MySQL/MariaDB-specific configuration."""

    driver = (
        config.driver
        .strip()
        .lower()
    )

    if driver not in {
        "mysql",
        "mariadb",
    }:
        raise DatabaseConfigurationError(
            "MySQL engine cannot use "
            f"driver: {config.driver}"
        )

    if not config.database.strip():
        raise DatabaseConfigurationError(
            "MySQL database name is required"
        )

    if not config.host or not config.host.strip():
        raise DatabaseConfigurationError(
            "MySQL host is required"
        )

    if not config.user or not config.user.strip():
        raise DatabaseConfigurationError(
            "MySQL user is required"
        )

    if config.port is None:
        raise DatabaseConfigurationError(
            "MySQL port is required"
        )

    if not 1 <= config.port <= 65535:
        raise DatabaseConfigurationError(
            "MySQL port must be between "
            "1 and 65535"
        )

    if config.connect_timeout <= 0:
        raise DatabaseConfigurationError(
            "MySQL connect timeout must "
            "be greater than zero"
        )

    normalize_tls_mode(
        config.tls_mode
    )


def _tls_ca_file() -> str | None:
    """Return configured CA certificate path."""

    value = os.environ.get(
        "DSM_DATABASE_TLS_CA",
        "",
    ).strip()

    if not value:
        return None

    path = (
        Path(value)
        .expanduser()
        .resolve()
    )

    if not path.is_file():
        raise DatabaseConfigurationError(
            "database TLS CA file not found: "
            f"{path}"
        )

    return str(path)


def tls_parameters(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Translate the Capivara TLS contract to Connector/Python."""

    mode = normalize_tls_mode(
        config.tls_mode
    )

    if mode == "disable":
        return {
            "ssl_disabled": True,
        }

    parameters: dict[str, Any] = {
        "ssl_disabled": False,
    }

    if mode == "preferred":
        return parameters

    if mode == "required":
        # Connector/Python doesn't expose the classic client's
        # ssl-mode argument for this API. Encryption is verified
        # after connection by _verify_tls_connection().
        return parameters

    ca_file = _tls_ca_file()

    if not ca_file:
        raise DatabaseConfigurationError(
            f"MySQL TLS mode {mode} requires "
            "DSM_DATABASE_TLS_CA"
        )

    parameters["ssl_ca"] = ca_file
    parameters["ssl_verify_cert"] = True

    if mode == "verify-full":
        parameters["ssl_verify_identity"] = True

    return parameters


def connection_parameters(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Build safe MySQL Connector/Python parameters."""

    validate_config(
        config
    )

    password = read_password_file(
        config.password_file
    )

    parameters: dict[str, Any] = {
        "host": config.host.strip(),
        "port": config.port,
        "database": config.database.strip(),
        "user": config.user.strip(),
        "connection_timeout": (
            config.connect_timeout
        ),
        "autocommit": False,
    }

    parameters.update(
        tls_parameters(
            config
        )
    )

    if password is not None:
        parameters["password"] = password

    return parameters


def _load_mysql_connector():
    """Load MySQL Connector/Python lazily."""

    try:
        connector = importlib.import_module(
            "mysql.connector"
        )

    except (
        ImportError,
        ModuleNotFoundError,
    ) as exc:
        raise DatabaseConfigurationError(
            "MySQL/MariaDB support requires "
            "mysql-connector-python. Install the "
            "optional MySQL database dependency."
        ) from exc

    connect_fn = getattr(
        connector,
        "connect",
        None,
    )

    if connect_fn is None:
        raise DatabaseConfigurationError(
            "installed mysql.connector does not "
            "expose connect()"
        )

    return connector


def _ssl_cipher(
    connection: Any,
) -> str:
    """Return the TLS cipher used by the current session."""

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            "SHOW STATUS LIKE 'Ssl_cipher'"
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if not row:
        return ""

    value = (
        row.get("Value")
        or row.get("VALUE")
        or row.get("value")
        or ""
    )

    return str(value).strip()


def _verify_tls_connection(
    connection: Any,
    config: DatabaseConfig,
) -> None:
    """Enforce Capivara TLS policy after connecting."""

    mode = normalize_tls_mode(
        config.tls_mode
    )

    if mode in {
        "disable",
        "preferred",
    }:
        return

    cipher = _ssl_cipher(
        connection
    )

    if not cipher:
        raise DatabaseConnectionError(
            "MySQL TLS is required but the "
            "connection is not encrypted"
        )


def connect(
    config: DatabaseConfig,
):
    """Open a MySQL/MariaDB connection."""

    parameters = connection_parameters(
        config
    )

    connector = (
        _load_mysql_connector()
    )

    try:
        connection = connector.connect(
            **parameters
        )

        _verify_tls_connection(
            connection,
            config,
        )

        return connection

    except DatabaseConnectionError:
        try:
            connection.close()
        except (
            Exception,
            UnboundLocalError,
        ):
            pass

        raise

    except Exception as exc:
        try:
            connection.close()
        except (
            Exception,
            UnboundLocalError,
        ):
            pass

        raise DatabaseConnectionError(
            "could not connect to MySQL/MariaDB: "
            f"{exc}"
        ) from exc

# =============================================================
# Migration tracking
# =============================================================

SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    checksum CHAR(64) NOT NULL,
    applied_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB
"""


def _serialize_value(
    value: Any,
) -> Any:
    """Normalize database values for JSON payloads."""

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return value


def _serialize_row(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a JSON-safe result row."""

    return {
        key: _serialize_value(value)
        for key, value in row.items()
    }


def _dictionary_cursor(
    connection: Any,
):
    """Open a dictionary cursor."""

    return connection.cursor(
        dictionary=True
    )


def _consume_result_sets(
    cursor: Any,
) -> None:
    """Consume remaining result sets from a multi-statement script."""

    nextset = getattr(
        cursor,
        "nextset",
        None,
    )

    if nextset is None:
        return

    while nextset():
        pass


def _execute_script(
    connection: Any,
    sql: str,
) -> None:
    """Execute a MySQL/MariaDB migration script.

    Connector/Python 9.2+ handles multi-statements and
    DELIMITER directives itself.
    """

    cursor = connection.cursor()

    try:
        cursor.execute(
            sql
        )

        _consume_result_sets(
            cursor
        )

    finally:
        cursor.close()


def applied_migrations(
    connection: Any,
) -> dict[int, dict[str, Any]]:
    """Return migrations recorded in the target database."""

    cursor = _dictionary_cursor(
        connection
    )

    try:
        cursor.execute(
            SCHEMA_MIGRATIONS_SQL
        )

        cursor.execute(
            """
            SELECT
                version,
                name,
                checksum,
                applied_at
            FROM schema_migrations
            ORDER BY version
            """
        )

        rows = cursor.fetchall()

    except Exception as exc:
        raise DatabaseMigrationError(
            "could not read MySQL/MariaDB "
            f"migration state: {exc}"
        ) from exc

    finally:
        cursor.close()

    return {
        int(row["version"]): (
            _serialize_row(row)
        )
        for row in rows
    }


def apply_migrations(
    connection: Any,
    migrations: Iterable[Migration] | None = None,
) -> list[int]:
    """Apply pending MySQL/MariaDB migrations.

    MySQL DDL can cause implicit commits. Therefore migration
    registration occurs only after the complete script succeeds,
    but DDL already accepted by the server cannot always be
    rolled back if a later statement fails.
    """

    migration_list = list(
        migrations
        or load_migrations()
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
            if (
                previous["checksum"]
                != migration.checksum
            ):
                raise DatabaseMigrationError(
                    "applied MySQL/MariaDB migration "
                    f"{migration.version:03d} "
                    "checksum does not match"
                )

            continue

        try:
            _execute_script(
                connection,
                migration.sql,
            )

            cursor = connection.cursor()

            try:
                cursor.execute(
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

            finally:
                cursor.close()

            connection.commit()

        except Exception as exc:
            try:
                connection.rollback()
            except Exception:
                pass

            raise DatabaseMigrationError(
                "MySQL/MariaDB migration "
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
    """Return whether schema_migrations exists."""

    cursor = _dictionary_cursor(
        connection
    )

    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS table_count
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = 'schema_migrations'
            """
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    return bool(
        row
        and int(
            row.get(
                "table_count",
                0,
            )
        ) > 0
    )


def detect_server_flavor(
    server_version: Any,
) -> str:
    """Identify MySQL or MariaDB from VERSION()."""

    if (
        server_version
        and "mariadb"
        in str(server_version).lower()
    ):
        return "mariadb"

    return "mysql"


def _database_status_connection(
    connection: Any,
    config: DatabaseConfig,
    *,
    applied_now: Iterable[int] = (),
) -> dict[str, Any]:
    """Build status using an existing connection."""

    cursor = _dictionary_cursor(
        connection
    )

    try:
        cursor.execute(
            """
            SELECT
                DATABASE() AS database_name,
                CURRENT_USER() AS user_name,
                VERSION() AS server_version
            """
        )

        server = cursor.fetchone()

    except Exception as exc:
        raise DatabaseConnectionError(
            "could not read MySQL/MariaDB "
            f"status: {exc}"
        ) from exc

    finally:
        cursor.close()

    initialized = (
        _schema_migrations_exists(
            connection
        )
    )

    migrations: list[
        dict[str, Any]
    ] = []

    if initialized:
        cursor = _dictionary_cursor(
            connection
        )

        try:
            cursor.execute(
                """
                SELECT
                    version,
                    name,
                    checksum,
                    applied_at
                FROM schema_migrations
                ORDER BY version
                """
            )

            migrations = [
                _serialize_row(row)
                for row
                in cursor.fetchall()
            ]

        finally:
            cursor.close()

    current_migration = (
        int(
            migrations[-1]["version"]
        )
        if migrations
        else 0
    )

    server_version = (
        server.get("server_version")
        if server
        else None
    )

    return {
        "schema_version": 1,
        "kind": "DatabaseStatus",
        "driver": "mysql",
        "server_flavor": (
            detect_server_flavor(
                server_version
            )
        ),
        "database": (
            server.get("database_name")
            if server
            else config.database
        ),
        "user": (
            server.get("user_name")
            if server
            else config.user
        ),
        "server_version": (
            server_version
        ),
        "connected": True,
        "initialized": initialized,
        "health": "ok",
        "current_migration": (
            current_migration
        ),
        "applied_migrations": (
            migrations
        ),
        "applied_now": list(
            applied_now
        ),
    }


def database_status(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Return MySQL/MariaDB schema status."""

    connection = connect(
        config
    )

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
    """Run basic MySQL/MariaDB health checks."""

    connection = connect(
        config
    )

    try:
        cursor = _dictionary_cursor(
            connection
        )

        try:
            cursor.execute(
                """
                SELECT
                    1 AS ok,
                    DATABASE() AS database_name,
                    CURRENT_USER() AS user_name,
                    VERSION() AS server_version
                """
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

        valid = bool(
            row
            and int(
                row.get(
                    "ok",
                    0,
                )
            ) == 1
        )

        server_version = (
            row.get("server_version")
            if row
            else None
        )

        return {
            "schema_version": 1,
            "kind": "DatabaseCheck",
            "driver": "mysql",
            "server_flavor": (
                detect_server_flavor(
                    server_version
                )
            ),
            "database": (
                row.get("database_name")
                if row
                else config.database
            ),
            "user": (
                row.get("user_name")
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
            "MySQL/MariaDB health "
            f"check failed: {exc}"
        ) from exc

    finally:
        connection.close()


def initialize(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Initialize MySQL/MariaDB and apply migrations."""

    connection = connect(
        config
    )

    try:
        completed = ([] if _schema_migrations_exists(connection)
                     else apply_consolidated_schema(connection, config.driver))
        validate_schema(connection)

        return _database_status_connection(
            connection,
            config,
            applied_now=completed,
        )

    finally:
        connection.close()


def migrate(
    config: DatabaseConfig,
) -> dict[str, Any]:
    """Apply pending MySQL/MariaDB migrations."""

    return initialize(
        config
    )
