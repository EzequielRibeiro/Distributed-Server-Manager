#!/usr/bin/env python3
"""SQLite persistence engine for Capivara DSM."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MIGRATION_PATTERN = re.compile(
    r"^(?P<version>[0-9]{3})_(?P<name>[a-z0-9_]+)\.sql$"
)

SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
)
"""

CONSOLIDATED_SCHEMA_VERSION = 41
CONSOLIDATED_SCHEMA_NAME = "consolidated_schema"
REQUIRED_SCHEMA_TABLES = {
    "agents", "controllers", "agent_pairing_tokens", "agent_credentials",
    "agent_runtime_inventory", "schema_migrations",
}


def consolidated_schema_path() -> Path:
    return Path(__file__).resolve().parent / "schemas" / "sqlite.sql"


def apply_consolidated_schema(connection: sqlite3.Connection) -> list[int]:
    """Create a new database from the supported complete schema."""
    path = consolidated_schema_path()
    if not path.is_file():
        raise DatabaseError(f"consolidated SQLite schema not found: {path}")
    sql = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    script = (
        "BEGIN IMMEDIATE;\n" + sql + "\n" + SCHEMA_MIGRATIONS_SQL + ";\n"
        "INSERT INTO schema_migrations(version,name,checksum) VALUES ("
        f"{CONSOLIDATED_SCHEMA_VERSION},'{CONSOLIDATED_SCHEMA_NAME}','{checksum}');\nCOMMIT;\n"
    )
    try:
        connection.executescript(script)
    except sqlite3.Error as exc:
        connection.rollback()
        raise DatabaseError(f"consolidated SQLite schema failed: {exc}") from exc
    return [CONSOLIDATED_SCHEMA_VERSION]


class DatabaseError(RuntimeError):
    """Raised when SQLite initialization or validation cannot continue."""


@dataclass(frozen=True)
class Migration:
    """One versioned SQLite schema migration."""

    version: int
    name: str
    path: Path
    sql: str
    checksum: str


def default_root() -> Path:
    """Return the configured Capivara root directory."""

    return Path(
        os.environ.get(
            "DSM_ROOT",
            Path(__file__).resolve().parents[1],
        )
    ).resolve()


def default_database(root: Path) -> Path:
    """Return the configured SQLite database path."""

    configured = os.environ.get("DSM_DATABASE")

    if configured:
        return Path(configured).resolve()

    return root / "data" / "capivara.db"


def migration_directory() -> Path:
    """Return the current SQLite migration directory."""

    return Path(__file__).resolve().parent / "migrations"


def load_migrations(
    directory: Path | None = None,
) -> list[Migration]:
    """Load and validate migrations in version order."""

    directory = directory or migration_directory()

    migrations: list[Migration] = []
    seen_versions: set[int] = set()

    if not directory.is_dir():
        raise DatabaseError(
            f"migration directory not found: {directory}"
        )

    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_PATTERN.fullmatch(path.name)

        if not match:
            raise DatabaseError(
                f"invalid migration filename: {path.name}"
            )

        version = int(match.group("version"))

        if version in seen_versions:
            raise DatabaseError(
                f"duplicate migration version: {version}"
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
        raise DatabaseError(
            "no database migrations were found"
        )

    return migrations


def connect(
    database: Path,
    *,
    create_parent: bool = True,
    timeout: int | float = 5,
) -> sqlite3.Connection:
    """Open a configured SQLite connection."""

    if create_parent:
        database.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    connection = sqlite3.connect(
        database,
        timeout=timeout,
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    connection.execute(
        "PRAGMA busy_timeout = 5000"
    )

    return connection


def _sql_literal(value: str) -> str:
    """Return a safely quoted internal SQL literal."""

    return "'" + value.replace("'", "''") + "'"


def applied_migrations(
    connection: sqlite3.Connection,
) -> dict[int, sqlite3.Row]:
    """Return migrations recorded by the database."""

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

    return {
        int(row["version"]): row
        for row in rows
    }


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Iterable[Migration] | None = None,
) -> list[int]:
    """Apply pending SQLite migrations atomically."""

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
                raise DatabaseError(
                    "applied migration "
                    f"{migration.version:03d} "
                    "checksum does not match"
                )

            continue

        tracking_sql = (
            "INSERT INTO schema_migrations"
            "(version, name, checksum) VALUES ("
            f"{migration.version}, "
            f"{_sql_literal(migration.name)}, "
            f"{_sql_literal(migration.checksum)}"
            ");"
        )

        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql}\n"
            f"{tracking_sql}\n"
            "COMMIT;\n"
        )

        try:
            connection.executescript(
                script
            )

        except sqlite3.Error as exc:
            connection.rollback()

            raise DatabaseError(
                "migration "
                f"{migration.version:03d}_"
                f"{migration.name} failed: {exc}"
            ) from exc

        completed.append(
            migration.version
        )

    return completed


def initialize(
    database: Path,
) -> dict[str, object]:
    """Initialize SQLite and apply pending migrations."""

    with closing(
        connect(database)
    ) as connection:
        connection.execute(
            "PRAGMA journal_mode = WAL"
        )

        connection.execute(
            "PRAGMA synchronous = NORMAL"
        )

        tables = set(_table_names(connection))
        completed = ([] if "schema_migrations" in tables
                     else apply_consolidated_schema(connection))

    return database_status(
        database,
        applied_now=completed,
    )


def _table_names(
    connection: sqlite3.Connection,
) -> list[str]:
    """Return user-defined SQLite table names."""

    return [
        str(row[0])
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]


def database_status(
    database: Path,
    *,
    applied_now: Iterable[int] = (),
) -> dict[str, object]:
    """Return SQLite schema and health status."""

    if not database.is_file():
        return {
            "schema_version": 1,
            "kind": "DatabaseStatus",
            "database": str(database),
            "initialized": False,
            "health": "missing",
            "current_migration": 0,
            "applied_migrations": [],
            "applied_now": list(applied_now),
            "tables": [],
        }

    with closing(
        connect(
            database,
            create_parent=False,
        )
    ) as connection:
        table_names = _table_names(
            connection
        )

        if "schema_migrations" not in table_names:
            migrations: list[
                dict[str, object]
            ] = []

        else:
            migrations = [
                dict(row)
                for row in connection.execute(
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
            ]

        quick_check = str(
            connection.execute(
                "PRAGMA quick_check"
            ).fetchone()[0]
        )

    return {
        "schema_version": 1,
        "kind": "DatabaseStatus",
        "database": str(database),
        "initialized": bool(migrations),
        "health": (
            "ok"
            if quick_check == "ok"
            else "error"
        ),
        "current_migration": (
            int(
                migrations[-1]["version"]
            )
            if migrations
            else 0
        ),
        "applied_migrations": migrations,
        "applied_now": list(applied_now),
        "tables": table_names,
    }


def check_database(
    database: Path,
) -> dict[str, object]:
    """Run SQLite integrity and initialization checks."""

    status = database_status(
        database
    )

    status["kind"] = "DatabaseCheck"

    status["valid"] = bool(status["initialized"] and status["health"] == "ok"
                           and REQUIRED_SCHEMA_TABLES.issubset(status["tables"]))

    return status


def backup_database(
    database: Path,
    destination: Path,
) -> dict[str, object]:
    """Create a consistent SQLite backup."""

    if not database.is_file():
        raise DatabaseError(
            f"database not found: {database}"
        )

    if destination.exists():
        raise DatabaseError(
            "backup destination already exists: "
            f"{destination}"
        )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with closing(
        connect(
            database,
            create_parent=False,
        )
    ) as source:
        with closing(
            sqlite3.connect(destination)
        ) as target:
            source.backup(
                target
            )

    return {
        "schema_version": 1,
        "kind": "DatabaseBackup",
        "database": str(database),
        "backup": str(destination),
        "size": destination.stat().st_size,
    }


def restore_database(database: Path, source: Path) -> dict[str, object]:
    """Atomically restore a validated SQLite backup."""
    if not source.is_file():
        raise DatabaseError(f"backup not found: {source}")
    with closing(connect(source, create_parent=False)) as candidate:
        integrity = candidate.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise DatabaseError("backup failed SQLite integrity_check")
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_name(database.name + ".restore-part")
    temporary.unlink(missing_ok=True)
    try:
        with closing(connect(source, create_parent=False)) as candidate:
            with closing(sqlite3.connect(temporary)) as target:
                candidate.backup(target)
        os.replace(temporary, database)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "schema_version": 1, "kind": "DatabaseRestore",
        "database": str(database), "backup": str(source),
        "size": database.stat().st_size,
    }
