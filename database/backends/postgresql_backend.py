#!/usr/bin/env python3
"""PostgreSQL DatabaseBackend implementation for Capivara DSM."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
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
        """Create a consistent custom-format backup using pg_dump."""
        target = Path(destination).expanduser().resolve()
        if target.exists():
            raise DatabaseError(f"backup destination already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        password = postgresql_engine.read_password_file(
            self.config.password_file
        )
        if password is not None:
            environment["PGPASSWORD"] = password
        environment["PGSSLMODE"] = postgresql_engine.normalize_sslmode(
            self.config.tls_mode
        )
        command = [
            "pg_dump", "--format=custom", "--no-owner", "--no-acl",
            "--host", str(self.config.host),
            "--port", str(self.config.port),
            "--username", str(self.config.user),
            "--file", str(target), str(self.config.database),
        ]
        try:
            subprocess.run(
                command, env=environment, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            )
            if not target.is_file():
                raise DatabaseError("pg_dump did not create the backup")
        except (FileNotFoundError, subprocess.CalledProcessError, OSError) as exc:
            target.unlink(missing_ok=True)
            raise DatabaseError(f"PostgreSQL backup failed: {exc}") from exc
        finally:
            environment.pop("PGPASSWORD", None)
        return {
            "schema_version": 1, "kind": "DatabaseBackup",
            "driver": self.name, "backup": str(target),
            "size": target.stat().st_size,
        }

    def restore(self, source: str) -> Mapping[str, Any]:
        """Restore a pg_dump custom-format backup using pg_restore."""
        backup = Path(source).expanduser().resolve()
        if not backup.is_file():
            raise DatabaseError(f"backup not found: {backup}")
        environment = os.environ.copy()
        password = postgresql_engine.read_password_file(
            self.config.password_file
        )
        if password is not None:
            environment["PGPASSWORD"] = password
        environment["PGSSLMODE"] = postgresql_engine.normalize_sslmode(
            self.config.tls_mode
        )
        command = [
            "pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl",
            "--single-transaction", "--host", str(self.config.host),
            "--port", str(self.config.port), "--username", str(self.config.user),
            "--dbname", str(self.config.database), str(backup),
        ]
        try:
            subprocess.run(
                command, env=environment, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, OSError) as exc:
            raise DatabaseError(f"PostgreSQL restore failed: {exc}") from exc
        finally:
            environment.pop("PGPASSWORD", None)
        return {
            "schema_version": 1, "kind": "DatabaseRestore",
            "driver": self.name, "backup": str(backup),
        }

    # =========================================================
    # Lifecycle
    # =========================================================

    def close(
        self,
    ) -> None:
        """No persistent PostgreSQL pool exists at this stage."""

        return None
