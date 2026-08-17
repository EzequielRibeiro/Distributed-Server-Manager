#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

sys.path.insert(0, str(DATABASE_DIR))

from backend import (
    DatabaseConfig,
    DatabaseConfigurationError,
)

from backend_factory import (
    canonicalize_database_config,
    create_backend,
    normalize_database_driver,
)


class DatabaseBackendFactoryTest(unittest.TestCase):

    def test_sqlite_alias(self):
        self.assertEqual(
            normalize_database_driver("sqlite3"),
            "sqlite",
        )

    def test_postgresql_aliases(self):
        self.assertEqual(
            normalize_database_driver("postgres"),
            "postgresql",
        )

        self.assertEqual(
            normalize_database_driver("pgsql"),
            "postgresql",
        )

    def test_mariadb_alias(self):
        self.assertEqual(
            normalize_database_driver("mariadb"),
            "mysql",
        )

    def test_driver_normalization_is_case_insensitive(self):
        self.assertEqual(
            normalize_database_driver(" PostgreSQL "),
            "postgresql",
        )

    def test_invalid_driver_is_rejected(self):
        with self.assertRaises(DatabaseConfigurationError):
            normalize_database_driver("oracle")

    def test_empty_driver_is_rejected(self):
        with self.assertRaises(DatabaseConfigurationError):
            normalize_database_driver("")

    def test_config_is_canonicalized(self):
        config = DatabaseConfig(
            driver="mariadb",
            database="capivara",
            host="db.internal",
            port=3306,
            user="capivara",
        )

        result = canonicalize_database_config(config)

        self.assertEqual(result.driver, "mysql")
        self.assertEqual(result.database, "capivara")
        self.assertEqual(result.host, "db.internal")
        self.assertEqual(result.port, 3306)
        self.assertEqual(result.user, "capivara")

    def test_create_sqlite_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "capivara.db"

            backend = create_backend(
                DatabaseConfig(
                    driver="sqlite",
                    database=str(database),
                )
            )

            try:
                self.assertEqual(
                    backend.name,
                    "sqlite",
                )

                self.assertFalse(
                    database.exists()
                )

            finally:
                backend.close()


if __name__ == "__main__":
    unittest.main()
