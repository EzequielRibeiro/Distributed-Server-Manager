#!/usr/bin/env python3
"""SQLite persistence and migration manager for Capivara DSM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MIGRATION_PATTERN = re.compile(r"^(?P<version>[0-9]{3})_(?P<name>[a-z0-9_]+)\.sql$")
SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""


class DatabaseError(RuntimeError):
    """Raised when database initialization or validation cannot continue."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str
    checksum: str


def default_root() -> Path:
    return Path(os.environ.get("DSM_ROOT", Path(__file__).resolve().parents[1])).resolve()


def default_database(root: Path) -> Path:
    configured = os.environ.get("DSM_DATABASE")
    return Path(configured).resolve() if configured else root / "data" / "capivara.db"


def migration_directory() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def load_migrations(directory: Path | None = None) -> list[Migration]:
    directory = directory or migration_directory()
    migrations: list[Migration] = []
    seen_versions: set[int] = set()

    if not directory.is_dir():
        raise DatabaseError(f"migration directory not found: {directory}")

    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_PATTERN.fullmatch(path.name)
        if not match:
            raise DatabaseError(f"invalid migration filename: {path.name}")
        version = int(match.group("version"))
        if version in seen_versions:
            raise DatabaseError(f"duplicate migration version: {version}")
        seen_versions.add(version)
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
                sql=sql,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )

    if not migrations:
        raise DatabaseError("no database migrations were found")
    return migrations


def connect(database: Path, *, create_parent: bool = True) -> sqlite3.Connection:
    if create_parent:
        database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def applied_migrations(connection: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    connection.execute(SCHEMA_MIGRATIONS_SQL)
    rows = connection.execute(
        "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {int(row["version"]): row for row in rows}


def apply_migrations(
    connection: sqlite3.Connection, migrations: Iterable[Migration] | None = None
) -> list[int]:
    migration_list = list(migrations or load_migrations())
    applied = applied_migrations(connection)
    completed: list[int] = []

    for migration in migration_list:
        previous = applied.get(migration.version)
        if previous:
            if previous["checksum"] != migration.checksum:
                raise DatabaseError(
                    f"applied migration {migration.version:03d} checksum does not match"
                )
            continue

        tracking_sql = (
            "INSERT INTO schema_migrations(version, name, checksum) VALUES ("
            f"{migration.version}, {_sql_literal(migration.name)}, "
            f"{_sql_literal(migration.checksum)});"
        )
        script = f"BEGIN IMMEDIATE;\n{migration.sql}\n{tracking_sql}\nCOMMIT;\n"
        try:
            connection.executescript(script)
        except sqlite3.Error as exc:
            connection.rollback()
            raise DatabaseError(
                f"migration {migration.version:03d}_{migration.name} failed: {exc}"
            ) from exc
        completed.append(migration.version)

    return completed


def initialize(database: Path) -> dict[str, object]:
    with closing(connect(database)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        completed = apply_migrations(connection)
    return database_status(database, applied_now=completed)


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def database_status(database: Path, *, applied_now: Iterable[int] = ()) -> dict[str, object]:
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

    with closing(connect(database, create_parent=False)) as connection:
        table_names = _table_names(connection)
        if "schema_migrations" not in table_names:
            migrations: list[dict[str, object]] = []
        else:
            migrations = [
                dict(row)
                for row in connection.execute(
                    "SELECT version, name, checksum, applied_at "
                    "FROM schema_migrations ORDER BY version"
                )
            ]
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])

    return {
        "schema_version": 1,
        "kind": "DatabaseStatus",
        "database": str(database),
        "initialized": bool(migrations),
        "health": "ok" if quick_check == "ok" else "error",
        "current_migration": int(migrations[-1]["version"]) if migrations else 0,
        "applied_migrations": migrations,
        "applied_now": list(applied_now),
        "tables": table_names,
    }


def check_database(database: Path) -> dict[str, object]:
    status = database_status(database)
    status["kind"] = "DatabaseCheck"
    status["valid"] = bool(status["initialized"] and status["health"] == "ok")
    return status


def backup_database(database: Path, destination: Path) -> dict[str, object]:
    if not database.is_file():
        raise DatabaseError(f"database not found: {database}")
    if destination.exists():
        raise DatabaseError(f"backup destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(database, create_parent=False)) as source:
        with closing(sqlite3.connect(destination)) as target:
            source.backup(target)
    return {
        "schema_version": 1,
        "kind": "DatabaseBackup",
        "database": str(database),
        "backup": str(destination),
        "size": destination.stat().st_size,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capivara DSM SQLite manager")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--database", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="create the database and apply migrations")
    subparsers.add_parser("migrate", help="apply pending migrations")
    subparsers.add_parser("status", help="show migration and database status")
    subparsers.add_parser("check", help="run SQLite integrity checks")
    backup_parser = subparsers.add_parser("backup", help="create a consistent SQLite backup")
    backup_parser.add_argument("destination", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    database = (args.database or default_database(root)).resolve()

    try:
        if args.command in {"init", "migrate"}:
            payload = initialize(database)
        elif args.command == "status":
            payload = database_status(database)
        elif args.command == "check":
            payload = check_database(database)
        elif args.command == "backup":
            payload = backup_database(database, args.destination.resolve())
        else:  # pragma: no cover - argparse prevents this branch.
            parser.error(f"unsupported command: {args.command}")
            return 2
    except (DatabaseError, OSError, sqlite3.Error) as exc:
        print(
            json.dumps(
                {"schema_version": 1, "kind": "DatabaseError", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.command == "check" and not payload["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
