#!/usr/bin/env python3
"""PostgreSQL DatabaseBackend implementation for Capivara DSM."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

import postgresql_engine

from backend import (
    DatabaseBackend,
    DatabaseConfig,
    DatabaseError,
)


class PostgreSQLBackend(DatabaseBackend):
    """PostgreSQL implementation of the Capivara database contract."""

    name = "postgresql"

    def __init__(
        self,
        config: DatabaseConfig,
    ):
        super().__init__(config)

        postgresql_engine.validate_config(
            config
        )

    # =========================================================
    # Connection
    # =========================================================

    @contextmanager
    def connect(
        self,
    ) -> Iterator[Any]:
        """Open a managed PostgreSQL connection."""

        connection = postgresql_engine.connect(
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
        """Open an atomic PostgreSQL transaction."""

        connection = postgresql_engine.connect(
            self.config
        )

        try:
            with connection.transaction():
                yield connection

        finally:
            connection.close()

    # =========================================================
    # Initialization / migrations
    # =========================================================

    def initialize(
        self,
    ) -> Mapping[str, Any]:
        """Initialize PostgreSQL and apply pending migrations."""

        return postgresql_engine.initialize(
            self.config
        )

    def migrate(
        self,
    ) -> Mapping[str, Any]:
        """Apply pending PostgreSQL migrations."""

        return postgresql_engine.migrate(
            self.config
        )

    # =========================================================
    # Status
    # =========================================================

    def status(
        self,
    ) -> Mapping[str, Any]:
        """Return PostgreSQL status."""

        return postgresql_engine.database_status(
            self.config
        )

    # =========================================================
    # Health
    # =========================================================

    def health_check(
        self,
    ) -> Mapping[str, Any]:
        """Run PostgreSQL health checks."""

        return postgresql_engine.check_database(
            self.config
        )

    # =========================================================
    # Schema
    # =========================================================

    def current_schema_version(
        self,
    ) -> int:
        """Return the current PostgreSQL migration version."""

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
        """Return PostgreSQL migrations already applied."""

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
                "invalid PostgreSQL "
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
        """Create a PostgreSQL backup.

        PostgreSQL backup support will be implemented
        separately using an appropriate backup provider.
        """

        raise DatabaseError(
            "PostgreSQL backup provider "
            "is not implemented yet"
        )

    # =========================================================
    # Lifecycle
    # =========================================================

    def close(
        self,
    ) -> None:
        """No persistent PostgreSQL pool exists at this stage."""

        return None
