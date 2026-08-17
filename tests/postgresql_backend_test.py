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

from backends.postgresql_backend import (
    PostgreSQLBackend,
)


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_entered += 1
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        self.connection.transaction_exited += 1
        return False


class FakeCursorResult:
    def __init__(
        self,
        *,
        one=None,
        all_rows=None,
    ):
        self.one = one
        self.all_rows = (
            all_rows
            if all_rows is not None
            else []
        )

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.all_rows


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.queries = []
        self.transaction_entered = 0
        self.transaction_exited = 0

    def close(self):
        self.closed = True

    def transaction(self):
        return FakeTransaction(
            self
        )

    def execute(
        self,
        sql,
        parameters=None,
    ):
        normalized = " ".join(
            sql.split()
        )

        self.queries.append(
            (
                normalized,
                parameters,
            )
        )

        if (
            "current_setting" in normalized
        ):
            return FakeCursorResult(
                one={
                    "database": "capivara",
                    "user": "capivara",
                    "server_version": "17.0",
                }
            )

        if (
            "information_schema.tables"
            in normalized
        ):
            return FakeCursorResult(
                one={
                    "exists": True,
                }
            )

        if (
            "FROM schema_migrations"
            in normalized
        ):
            return FakeCursorResult(
                all_rows=[
                    {
                        "version": 1,
                        "name": "initial",
                        "checksum": "a" * 64,
                        "applied_at": (
                            "2026-08-17T00:00:00Z"
                        ),
                    },
                    {
                        "version": 10,
                        "name": "alert_persistence",
                        "checksum": "b" * 64,
                        "applied_at": (
                            "2026-08-17T00:01:00Z"
                        ),
                    },
                ]
            )

        if "SELECT 1 AS ok" in normalized:
            return FakeCursorResult(
                one={
                    "ok": 1,
                    "database": "capivara",
                    "user": "capivara",
                }
            )

        return FakeCursorResult()


class PostgreSQLBackendTest(
    unittest.TestCase
):

    def config(
        self,
    ) -> DatabaseConfig:
        return DatabaseConfig(
            driver="postgresql",
            database="capivara",
            host="db.internal",
            port=5432,
            user="capivara",
            tls_mode="preferred",
            connect_timeout=5,
        )

    def test_backend_name(self):
        backend = PostgreSQLBackend(
            self.config()
        )

        self.assertEqual(
            backend.name,
            "postgresql",
        )

    def test_connect_closes_connection(self):
        connection = FakeConnection()

        with patch(
            "postgresql_engine.connect",
            return_value=connection,
        ):
            backend = PostgreSQLBackend(
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

    def test_transaction_uses_native_transaction_context(self):
        connection = FakeConnection()

        with patch(
            "postgresql_engine.connect",
            return_value=connection,
        ):
            backend = PostgreSQLBackend(
                self.config()
            )

            with backend.transaction() as result:
                self.assertIs(
                    result,
                    connection,
                )

        self.assertEqual(
            connection.transaction_entered,
            1,
        )

        self.assertEqual(
            connection.transaction_exited,
            1,
        )

        self.assertTrue(
            connection.closed
        )

    def test_transaction_closes_after_exception(self):
        connection = FakeConnection()

        with patch(
            "postgresql_engine.connect",
            return_value=connection,
        ):
            backend = PostgreSQLBackend(
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
            connection.transaction_entered,
            1,
        )

        self.assertEqual(
            connection.transaction_exited,
            1,
        )

        self.assertTrue(
            connection.closed
        )

    def test_status(self):
        connection = FakeConnection()

        with patch(
            "postgresql_engine.connect",
            return_value=connection,
        ):
            backend = PostgreSQLBackend(
                self.config()
            )

            result = backend.status()

        self.assertEqual(
            result["driver"],
            "postgresql",
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
            "postgresql_engine.connect",
            return_value=connection,
        ):
            backend = PostgreSQLBackend(
                self.config()
            )

            result = (
                backend.health_check()
            )

        self.assertEqual(
            result["driver"],
            "postgresql",
        )

        self.assertTrue(
            result["connected"]
        )

        self.assertTrue(
            result["valid"]
        )

        self.assertEqual(
            result["health"],
            "ok",
        )

    def test_current_schema_version(self):
        connection = FakeConnection()

        with patch(
            "postgresql_engine.connect",
            return_value=connection,
        ):
            backend = PostgreSQLBackend(
                self.config()
            )

            self.assertEqual(
                backend.current_schema_version(),
                10,
            )

    def test_applied_migrations(self):
        connection = FakeConnection()

        with patch(
            "postgresql_engine.connect",
            return_value=connection,
        ):
            backend = PostgreSQLBackend(
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
            "postgresql_engine.initialize",
            return_value=expected,
        ):
            backend = PostgreSQLBackend(
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
            "postgresql_engine.migrate",
            return_value=expected,
        ):
            backend = PostgreSQLBackend(
                self.config()
            )

            result = backend.migrate()

        self.assertEqual(
            result,
            expected,
        )

    def test_backup_uses_pg_dump_without_password_argument(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "backup.dump"

            def run(command, **kwargs):
                Path(command[command.index("--file") + 1]).write_bytes(b"dump")

            with patch("subprocess.run", side_effect=run) as runner:
                result = PostgreSQLBackend(self.config()).backup(str(target))
            command = runner.call_args.args[0]
            self.assertEqual(command[0], "pg_dump")
            self.assertNotIn("password", " ".join(command).lower())
            self.assertEqual(result["size"], 4)

    def test_restore_uses_pg_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "backup.dump"
            source.write_bytes(b"dump")
            with patch("subprocess.run") as runner:
                result = PostgreSQLBackend(self.config()).restore(str(source))
            command = runner.call_args.args[0]
            self.assertEqual(command[0], "pg_restore")
            self.assertIn("--single-transaction", command)
            self.assertEqual(result["kind"], "DatabaseRestore")

    def test_close_is_safe(self):
        backend = PostgreSQLBackend(
            self.config()
        )

        self.assertIsNone(
            backend.close()
        )


if __name__ == "__main__":
    unittest.main()
