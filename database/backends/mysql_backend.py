#!/usr/bin/env python3
"""MySQL/MariaDB DatabaseBackend implementation for Capivara DSM."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

import mysql_engine

from backend import (
    DatabaseBackend,
    DatabaseConfig,
    DatabaseError,
    DatabaseMigrationError,
)


class MySQLBackend(DatabaseBackend):
    """MySQL/MariaDB implementation of the Capivara database contract."""

    name = "mysql"

    def __init__(
        self,
        config: DatabaseConfig,
    ):
        super().__init__(config)

        mysql_engine.validate_config(
            config
        )

    # =========================================================
    # Connection
    # =========================================================

    @contextmanager
    def connect(
        self,
    ) -> Iterator[Any]:
        """Open a managed MySQL/MariaDB connection."""

        connection = mysql_engine.connect(
            self.config
        )

        try:
            yield connection

        finally:
            connection.close()

    # =========================================================
    # Transaction
    # =========================================================

    @contextmanager
    def transaction(
        self,
    ) -> Iterator[Any]:
        """Open an atomic MySQL/MariaDB transaction."""

        connection = mysql_engine.connect(
            self.config
        )

        try:
            connection.start_transaction()

            try:
                yield connection

            except Exception:
                connection.rollback()
                raise

            else:
                connection.commit()

        finally:
            connection.close()

    # =========================================================
    # Initialization / migrations
    # =========================================================

    def initialize(
        self,
    ) -> Mapping[str, Any]:
        """Initialize MySQL/MariaDB and apply migrations."""

        return mysql_engine.initialize(
            self.config

        )

    def migrate(
        self,
    ) -> Mapping[str, Any]:
        """Apply pending MySQL/MariaDB migrations."""

        return mysql_engine.migrate(
            self.config
        )

    # =========================================================
    # Status
    # =========================================================

    def status(
        self,
    ) -> Mapping[str, Any]:
        """Return MySQL/MariaDB status."""

        return mysql_engine.database_status(
            self.config
        )

    # =========================================================
    # Health
    # =========================================================

    def health_check(
        self,
    ) -> Mapping[str, Any]:
        """Run MySQL/MariaDB health checks."""

        return mysql_engine.check_database (
            self.config
        )

    # =========================================================
    # Schema
    # =========================================================

    def current_schema_version(
        self,
    ) -> int:
        """Return the current MySQL/MariaDB migration version."""

        status = self.status()

        return int(
            status.get(
                "current_migration",
                0,
            )
        )

    def applied_migrations(
        self,
    ) -> Sequence[Mapping[str, Any]]:
        """Return MySQL/MariaDB migrations already applied."""

        status = self.status()

        migrations = status.get(
            "applied_migrations",
            [],
        )

        if not isinstance(
            migrations,
            list,
        ):
            raise DatabaseError(
                "invalid MySQL/MariaDB "
                "applied_migrations payload"
            )

        return migrations

    # =========================================================
    # Backup
    # =========================================================

    def backup(
        self,
        destination: str,
    ) -> Mapping[str, Any]:
        """Create a MySQL/MariaDB backup.

        Backup provider support will be implemented separately.
        """

        raise DatabaseError(
            "MySQL/MariaDB backup provider "
            "is not implemented yet"
        )

    # =========================================================
    # Lifecycle
    # =========================================================

    def close(
        self,
    ) -> None:
        """No persistent MySQL connection pool exists yet."""

        return None
