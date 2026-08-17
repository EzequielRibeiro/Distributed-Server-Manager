#!/usr/bin/env python3
"""MySQL/MariaDB DatabaseBackend implementation for Capivara DSM."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
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
        """Create a consistent SQL backup using mysqldump."""
        target = Path(destination).expanduser().resolve()
        if target.exists():
            raise DatabaseError(f"backup destination already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        password = mysql_engine.read_password_file(self.config.password_file)
        if password is not None:
            environment["MYSQL_PWD"] = password
        tls_mode = mysql_engine.normalize_tls_mode(self.config.tls_mode)
        tls_argument = {
            "disable": "DISABLED", "preferred": "PREFERRED",
            "required": "REQUIRED", "verify-ca": "VERIFY_CA",
            "verify-full": "VERIFY_IDENTITY",
        }[tls_mode]
        command = [
            "mysqldump", "--single-transaction", "--routines", "--triggers",
            f"--ssl-mode={tls_argument}",
            "--host", str(self.config.host),
            "--port", str(self.config.port),
            "--user", str(self.config.user),
            str(self.config.database),
        ]
        try:
            with target.open("xb") as output:
                subprocess.run(
                    command, env=environment, check=True, stdout=output,
                    stderr=subprocess.PIPE,
                )
            if not target.is_file():
                raise DatabaseError("mysqldump did not create the backup")
        except (FileExistsError, FileNotFoundError,
                subprocess.CalledProcessError, OSError) as exc:
            target.unlink(missing_ok=True)
            raise DatabaseError(f"MySQL/MariaDB backup failed: {exc}") from exc
        finally:
            environment.pop("MYSQL_PWD", None)
        return {
            "schema_version": 1, "kind": "DatabaseBackup",
            "driver": self.name, "backup": str(target),
            "size": target.stat().st_size,
        }

    def restore(self, source: str) -> Mapping[str, Any]:
        """Restore a mysqldump SQL backup using the mysql client."""
        backup = Path(source).expanduser().resolve()
        if not backup.is_file():
            raise DatabaseError(f"backup not found: {backup}")
        environment = os.environ.copy()
        password = mysql_engine.read_password_file(self.config.password_file)
        if password is not None:
            environment["MYSQL_PWD"] = password
        tls_mode = mysql_engine.normalize_tls_mode(self.config.tls_mode)
        tls_argument = {
            "disable": "DISABLED", "preferred": "PREFERRED",
            "required": "REQUIRED", "verify-ca": "VERIFY_CA",
            "verify-full": "VERIFY_IDENTITY",
        }[tls_mode]
        command = [
            "mysql", f"--ssl-mode={tls_argument}",
            "--host", str(self.config.host), "--port", str(self.config.port),
            "--user", str(self.config.user), str(self.config.database),
        ]
        try:
            with backup.open("rb") as source_file:
                subprocess.run(
                    command, env=environment, check=True, stdin=source_file,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
        except (FileNotFoundError, subprocess.CalledProcessError, OSError) as exc:
            raise DatabaseError(f"MySQL/MariaDB restore failed: {exc}") from exc
        finally:
            environment.pop("MYSQL_PWD", None)
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
        """No persistent MySQL connection pool exists yet."""

        return None
