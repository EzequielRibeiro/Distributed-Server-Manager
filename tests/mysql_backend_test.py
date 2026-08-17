#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

sys.path.insert(
    0,
    str(DATABASE_DIR),
)


from backend import (
    DatabaseConfig,
    DatabaseError,
    DatabaseMigrationError,
)

from backends.mysql_backend import (
    MySQLBackend,
)


class FakeCursor:

    def __init__(self):
        self.closed = False
        self.query = ""

    def execute(
        self,
        sql,
        parameters=None,
    ):
        self.query = " ".join(
            sql.split()
        )

    def fetchone(self):
        if (
            "DATABASE() AS database_name"
            in self.query
            and "1 AS ok" not in self.query
        ):
            return {
                "database_name": "capivara",
                "user_name": "capivara@localhost",
                "server_version": "8.4.0",
            }

        if (
            "information_schema.tables"
            in self.query
        ):
            return {
                "table_count": 1,
            }

        if "1 AS ok" in self.query:
            return {
                "ok": 1,
                "database_name": "capivara",
                "user_name": "capivara@localhost",
                "server_version": "8.4.0",
            }

        return None

    def fetchall(self):
        if (
            "FROM schema_migrations"
            in self.query
        ):
            return [
                {
                    "version": 1,
                    "name": "initial",
                    "checksum": "a" * 64,
                    "applied_at": (
                        "2026-08-17 10:00:00"
                    ),
                },
                {
                    "version": 10,
                    "name": "alert_persistence",
                    "checksum": "b" * 64,
                    "applied_at": (
                        "2026-08-17 10:01:00"
                    ),
                },
            ]

        return []

    def close(self):
        self.closed = True


class FakeConnection:

    def __init__(self):
        self.closed = False
        self.started = 0
        self.commits = 0
        self.rollbacks = 0
        self.cursor_calls = []

    def cursor(
        self,
        **kwargs,
    ):
        self.cursor_calls.append(
            kwargs
        )

        return FakeCursor()

    def start_transaction(self):
        self.started += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class MySQLBackendTest(
    unittest.TestCase
):

    def config(
        self,
        **overrides,
    ) -> DatabaseConfig:

        values = {
            "driver": "mysql",
            "database": "capivara",
            "host": "db.internal",
            "port": 3306,
            "user": "capivara",
            "password_file": None,
            "tls_mode": "preferred",
            "connect_timeout": 5,
        }

        values.update(
            overrides
        )

        return DatabaseConfig(
            **values
        )

    def test_backend_name(self):
        backend = MySQLBackend(
            self.config()
        )

        self.assertEqual(
            backend.name,
            "mysql",
        )

    def test_mariadb_config_is_accepted(self):
        backend = MySQLBackend(
            self.config(
                driver="mariadb"
            )
        )

        self.assertEqual(
            backend.name,
            "mysql",
        )

    def test_connect_closes_connection(self):
        connection = FakeConnection()

        with patch(
            "mysql_engine.connect",
            return_value=connection,
        ):
            backend = MySQLBackend(
                self.config()
            )

            with backend.connect() as result:
                self.assertIs(
                    result,
                    connection,
                )

                self.assertFalse(
                    connection.closed
                )

        self.assertTrue(
            connection.closed
        )

    def test_transaction_commits(self):
        connection = FakeConnection()

        with patch(
            "mysql_engine.connect",
            return_value=connection,
        ):
            backend = MySQLBackend(
                self.config()
            )

            with backend.transaction() as result:
                self.assertIs(
                    result,
                    connection,
                )

        self.assertEqual(
            connection.started,
            1,
        )

        self.assertEqual(
            connection.commits,
            1,
        )

        self.assertEqual(
            connection.rollbacks,
            0,
        )

        self.assertTrue(
            connection.closed
        )

    def test_transaction_rolls_back_on_exception(self):
        connection = FakeConnection()

        with patch(
            "mysql_engine.connect",
            return_value=connection,
        ):
            backend = MySQLBackend(
                self.config()
            )

            with self.assertRaises(
                RuntimeError
            ):
                with backend.transaction():
                    raise RuntimeError(
                        "force rollback"
                    )

        self.assertEqual(
            connection.started,
            1,
        )

        self.assertEqual(
            connection.commits,
            0,
        )

        self.assertEqual(
            connection.rollbacks,
            1,
        )

        self.assertTrue(
            connection.closed
        )

    def test_status(self):
        connection = FakeConnection()

        with patch(
            "mysql_engine.connect",
            return_value=connection,
        ):
            backend = MySQLBackend(
                self.config()
            )

            result = backend.status()

        self.assertEqual(
            result["driver"],
            "mysql",
        )

        self.assertEqual(
            result["server_flavor"],
            "mysql",
        )

        self.assertTrue(
            result["connected"]
        )

        self.assertTrue(
            result["initialized"]
        )

        self.assertEqual(
            result["health"],
            "ok",
        )

        self.assertEqual(
            result["current_migration"],
            10,
        )

        self.assertEqual(
            len(
                result["applied_migrations"]
            ),
            2,
        )

    def test_health_check(self):
        connection = FakeConnection()

        with patch(
            "mysql_engine.connect",
            return_value=connection,
        ):
            backend = MySQLBackend(
                self.config()
            )

            result = (
                backend.health_check()
            )

        self.assertTrue(
            result["valid"]
        )

        self.assertTrue(
            result["connected"]
        )

        self.assertEqual(
            result["health"],
            "ok",
        )

        self.assertEqual(
            result["server_flavor"],
            "mysql",
        )

    def test_current_schema_version(self):
        connection = FakeConnection()

        with patch(
            "mysql_engine.connect",
            return_value=connection,
        ):
            backend = MySQLBackend(
                self.config()
            )

            self.assertEqual(
                backend.current_schema_version(),
                10,
            )

    def test_applied_migrations(self):
        connection = FakeConnection()

        with patch(
            "mysql_engine.connect",
            return_value=connection,
        ):
            backend = MySQLBackend(
                self.config()
            )

            result = list(
                backend.applied_migrations()
            )

        self.assertEqual(
            len(result),
            2,
        )

        self.assertEqual(
            result[-1]["version"],
            10,
        )

    def test_initialize_uses_engine(self):
        expected = {
            "initialized": True,
            "current_migration": 10,
        }

        with patch(
            "mysql_engine.initialize",
            return_value=expected,
        ):
            backend = MySQLBackend(
                self.config()
            )

            result = backend.initialize()

        self.assertEqual(
            result,
            expected,
        )

    def test_migrate_uses_engine(self):
        expected = {
            "initialized": True,
            "current_migration": 10,
            "applied_now": [],
        }

        with patch(
            "mysql_engine.migrate",
            return_value=expected,
        ):
            backend = MySQLBackend(
                self.config()
            )

            result = backend.migrate()

        self.assertEqual(
            result,
            expected,
        )

    def test_backup_uses_mysqldump_without_password_argument(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "backup.sql"
            with patch("subprocess.run") as runner:
                result = MySQLBackend(self.config()).backup(str(target))
            command = runner.call_args.args[0]
            self.assertEqual(command[0], "mysqldump")
            self.assertNotIn("password", " ".join(command).lower())
            self.assertTrue(target.is_file())
            self.assertEqual(result["driver"], "mysql")

    def test_restore_uses_mysql_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "backup.sql"
            source.write_bytes(b"SELECT 1;")
            with patch("subprocess.run") as runner:
                result = MySQLBackend(self.config()).restore(str(source))
            command = runner.call_args.args[0]
            self.assertEqual(command[0], "mysql")
            self.assertEqual(result["kind"], "DatabaseRestore")

    def test_close_is_safe(self):
        backend = MySQLBackend(
            self.config()
        )

        self.assertIsNone(
            backend.close()
        )


if __name__ == "__main__":
    unittest.main()
