#!/usr/bin/env python3

from __future__ import annotations

from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

sys.path.insert(0, str(DATABASE_DIR))

import manager


class DatabaseManagerCompatibilityTest(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

        self.database = (
            Path(self.temp.name)
            / "data"
            / "capivara.db"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_initialize(self):
        result = manager.initialize(
            self.database
        )

        self.assertTrue(
            result["initialized"]
        )

    def test_legacy_connect(self):
        manager.initialize(
            self.database
        )

        with closing(
            manager.connect(
                self.database
            )
        ) as connection:
            row = connection.execute(
                "SELECT 1"
            ).fetchone()

        self.assertEqual(
            row[0],
            1,
        )

    def test_legacy_status(self):
        manager.initialize(
            self.database
        )

        result = manager.database_status(
            self.database
        )

        self.assertEqual(
            result["health"],
            "ok",
        )

    def test_legacy_check(self):
        manager.initialize(
            self.database
        )

        result = manager.check_database(
            self.database
        )

        self.assertTrue(
            result["valid"]
        )

    def test_legacy_backup(self):
        manager.initialize(
            self.database
        )

        destination = (
            Path(self.temp.name)
            / "backup"
            / "capivara.db"
        )

        result = manager.backup_database(
            self.database,
            destination,
        )

        self.assertTrue(
            destination.is_file()
        )

        self.assertGreater(
            result["size"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
