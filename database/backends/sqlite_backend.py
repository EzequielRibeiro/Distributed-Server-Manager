#!/usr/bin/env python3
"""SQLite DatabaseBackend implementation for Capivara DSM."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import sqlite_engine

from backend import (
    DatabaseBackend,
    DatabaseConfig,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseError,
    DatabaseMigrationError,
)


class SQLiteBackend(DatabaseBackend):
    """SQLite implementation of the Capivara database contract."""

    name = "sqlite"

    def __init__(
        self,
        config: DatabaseConfig,
    ):
        super().__init__(config)

        driver = (
            config.driver
            .strip()
            .lower()
        )

        if driver not in {
            "sqlite",
            "sqlite3",
        }:
            raise DatabaseConfigurationError(
                "SQLiteBackend cannot use driver: "
                f"{config.driver}"
            )

        if not config.database:
            raise DatabaseConfigurationError(
                "SQLite database path is required"
            )

        if config.connect_timeout <= 0:
            raise DatabaseConfigurationError(
                "database connect_timeout "
                "must be greater than zero"
            )

        self.database_path = (
            Path(config.database)
            .expanduser()
            .resolve()
        )

    @contextmanager
    def connect(
        self,
    ) -> Iterator[sqlite3.Connection]:
        """Open a managed SQLite connection."""

        try:
            connection = (
                sqlite_engine.connect(
                    self.database_path,
                    timeout=self.config.connect_timeout,
                )
            )

        except (
            OSError,
            sqlite3.Error,
        ) as exc:
            raise DatabaseConnectionError(
                "could not connect to SQLite "
                f"database {self.database_path}: "
                f"{exc}"
            ) from exc

        try:
            yield connection

        finally:
            connection.close()

    @contextmanager
    def transaction(
        self,
    ) -> Iterator[sqlite3.Connection]:
        """Open an atomic SQLite transaction."""

        try:
            connection = (
                sqlite_engine.connect(
                    self.database_path,
                    timeout=self.config.connect_timeout,
                )
            )

        except (
            OSError,
            sqlite3.Error,
        ) as exc:
            raise DatabaseConnectionError(
                "could not open SQLite "
                f"transaction: {exc}"
            ) from exc

        try:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            yield connection

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def initialize(
        self,
    ) -> Mapping[str, Any]:
        """Initialize SQLite and apply pending migrations."""

        try:
            return sqlite_engine.initialize(
                self.database_path
            )

        except sqlite_engine.DatabaseError as exc:
            raise DatabaseMigrationError(
                str(exc)
            ) from exc

        except (
            OSError,
            sqlite3.Error,
        ) as exc:
            raise DatabaseError(
                "SQLite initialization failed: "
                f"{exc}"
            ) from exc

    def migrate(
        self,
    ) -> Mapping[str, Any]:
        """Apply only pending SQLite migrations."""

        return self.initialize()

    def status(
        self,
    ) -> Mapping[str, Any]:
        """Return SQLite database status."""

        try:
            result = dict(
                sqlite_engine.database_status(
                    self.database_path
                )
            )

        except (
            sqlite_engine.DatabaseError,
            OSError,
            sqlite3.Error,
        ) as exc:
            raise DatabaseError(
                "could not read SQLite status: "
                f"{exc}"
            ) from exc

        result["driver"] = self.name

        return result

    def health_check(
        self,
    ) -> Mapping[str, Any]:
        """Run SQLite integrity checks."""

        try:
            result = dict(
                sqlite_engine.check_database(
                    self.database_path
                )
            )

        except (
            sqlite_engine.DatabaseError,
            OSError,
            sqlite3.Error,
        ) as exc:
            raise DatabaseConnectionError(
                "SQLite health check failed: "
                f"{exc}"
            ) from exc

        result["driver"] = self.name

        result["connected"] = (
            result.get("health")
            != "missing"
        )

        return result

    def current_schema_version(
        self,
    ) -> int:
        """Return the current SQLite migration version."""

        result = self.status()

        return int(
            result.get(
                "current_migration",
                0,
            )
        )

    def applied_migrations(
        self,
    ) -> Sequence[Mapping[str, Any]]:
        """Return migrations already applied to SQLite."""

        result = self.status()

        migrations = result.get(
            "applied_migrations",
            [],
        )

        if not isinstance(
            migrations,
            list,
        ):
            raise DatabaseError(
                "invalid applied_migrations payload"
            )

        return migrations

    def backup(
        self,
        destination: str,
    ) -> Mapping[str, Any]:
        """Create a consistent SQLite backup."""

        destination_path = (
            Path(destination)
            .expanduser()
            .resolve()
        )

        try:
            result = dict(
                sqlite_engine.backup_database(
                    self.database_path,
                    destination_path,
                )
            )

        except (
            sqlite_engine.DatabaseError,
            OSError,
            sqlite3.Error,
        ) as exc:
            raise DatabaseError(
                "SQLite backup failed: "
                f"{exc}"
            ) from exc

        result["driver"] = self.name

        return result

    def restore(self, source: str) -> Mapping[str, Any]:
        """Atomically restore a validated SQLite backup."""
        try:
            result = dict(sqlite_engine.restore_database(
                self.database_path,
                Path(source).expanduser().resolve(),
            ))
        except (sqlite_engine.DatabaseError, OSError, sqlite3.Error) as exc:
            raise DatabaseError(f"SQLite restore failed: {exc}") from exc
        result["driver"] = self.name
        return result

    def close(
        self,
    ) -> None:
        """SQLite has no persistent connection pool."""

        return None
