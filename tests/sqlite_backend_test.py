#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

sys.path.insert(
    0,
    str(DATABASE_DIR),
)

from backend import DatabaseConfig
from backends.sqlite_backend import SQLiteBackend


class SQLiteBackendTest(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

        self.database = (
            Path(self.temp.name)
            / "data"
            / "capivara.db"
        )

        self.backend = SQLiteBackend(
            DatabaseConfig(
                driver="sqlite",
                database=str(self.database),
            )
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_backend_name(self):
        self.assertEqual(
            self.backend.name,
            "sqlite",
        )

    def test_initialization(self):
        status = self.backend.initialize()

        self.assertTrue(
            status["initialized"]
        )

        self.assertGreater(
            status["current_migration"],
            0,
        )

    def test_initialization_is_idempotent(self):
        first = self.backend.initialize()
        second = self.backend.initialize()

        self.assertTrue(
            first["initialized"]
        )

        self.assertEqual(
            second["applied_now"],
            [],
        )

    def test_health_check(self):
        self.backend.initialize()

        result = self.backend.health_check()

        self.assertEqual(
            result["driver"],
            "sqlite",
        )

        self.assertTrue(
            result["valid"]
        )

        self.assertTrue(
            result["connected"]
        )

    def test_schema_version(self):
        self.backend.initialize()

        self.assertGreater(
            self.backend.current_schema_version(),
            0,
        )

    def test_transaction_commit(self):
        self.backend.initialize()

        with self.backend.transaction() as connection:
            connection.execute(
                """
                INSERT INTO nodes(
                    id,
                    name,
                    role
                )
                VALUES (?, ?, ?)
                """,
                (
                    "sqlite-backend-test",
                    "SQLite Backend Test",
                    "agent",
                ),
            )

        with self.backend.connect() as connection:
            row = connection.execute(
                """
                SELECT name
                FROM nodes
                WHERE id = ?
                """,
                ("sqlite-backend-test",),
            ).fetchone()

        self.assertIsNotNone(row)

        self.assertEqual(
            row["name"],
            "SQLite Backend Test",
        )

    def test_transaction_rollback(self):
        self.backend.initialize()

        with self.assertRaises(RuntimeError):

            with self.backend.transaction() as connection:

                connection.execute(
                    """
                    INSERT INTO nodes(
                        id,
                        name,
                        role
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        "rollback-test",
                        "Rollback Test",
                        "agent",
                    ),
                )

                raise RuntimeError(
                    "force rollback"
                )

        with self.backend.connect() as connection:

            row = connection.execute(
                """
                SELECT id
                FROM nodes
                WHERE id = ?
                """,
                ("rollback-test",),
            ).fetchone()

        self.assertIsNone(row)

    def test_backup(self):
        self.backend.initialize()

        destination = (
            Path(self.temp.name)
            / "backup"
            / "capivara.db"
        )

        result = self.backend.backup(
            str(destination)
        )

        self.assertEqual(
            result["driver"],
            "sqlite",
        )

        self.assertTrue(
            destination.is_file()
        )

        self.assertGreater(
            result["size"],
            0,
        )

    def test_restore_replaces_database_atomically(self):
        self.backend.initialize()
        destination = Path(self.temp.name) / "backup" / "capivara.db"
        self.backend.backup(str(destination))
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                ("after-backup", "After Backup", "agent"),
            )
        result = self.backend.restore(str(destination))
        self.assertEqual(result["kind"], "DatabaseRestore")
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM nodes WHERE id=?", ("after-backup",)
            ).fetchone()
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
