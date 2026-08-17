#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

sys.path.insert(0, str(DATABASE_DIR))

from backend import (
    DatabaseConfig,
    DatabaseConfigurationError,
)
from runtime_backend import (
    backend_from_environment,
    database_config_from_environment,
)


class RuntimeBackendTest(unittest.TestCase):

    def test_sqlite_is_the_default_driver(self):
        with patch(
            "runtime_backend.sqlite_engine.default_root",
            return_value=Path("/srv/dsm"),
        ):
            config = database_config_from_environment({})

        self.assertEqual(config.driver, "sqlite")
        self.assertEqual(
            config.database,
            str(
                Path("/srv/dsm/data/capivara.db").resolve()
            ),
        )

    def test_sqlite_uses_dsm_database(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "capivara.db"

            config = database_config_from_environment(
                {
                    "DSM_DATABASE_DRIVER": "sqlite3",
                    "DSM_DATABASE": str(database),
                }
            )

        self.assertEqual(config.driver, "sqlite")
        self.assertEqual(
            config.database,
            str(database.resolve()),
        )
        self.assertIsNone(config.host)
        self.assertIsNone(config.port)

    def test_postgresql_config(self):
        config = database_config_from_environment(
            {
                "DSM_DATABASE_DRIVER": "postgres",
                "DSM_DATABASE_HOST": " db.internal ",
                "DSM_DATABASE_PORT": "5544",
                "DSM_DATABASE_NAME": "dsm_production",
                "DSM_DATABASE_USER": " dsm ",
                "DSM_DATABASE_PASSWORD_FILE": " /run/secrets/db ",
                "DSM_DATABASE_TLS": " REQUIRE ",
            }
        )

        self.assertEqual(
            config,
            DatabaseConfig(
                driver="postgresql",
                database="dsm_production",
                host="db.internal",
                port=5544,
                user="dsm",
                password_file="/run/secrets/db",
                tls_mode="require",
                connect_timeout=5,
            ),
        )

    def test_postgresql_defaults(self):
        config = database_config_from_environment(
            {
                "DSM_DATABASE_DRIVER": "postgresql",
                "DSM_DATABASE_HOST": "db.internal",
                "DSM_DATABASE_USER": "dsm",
            }
        )

        self.assertEqual(config.database, "capivara")
        self.assertEqual(config.port, 5432)
        self.assertEqual(config.tls_mode, "preferred")

    def test_mariadb_uses_mysql_backend_config(self):
        config = database_config_from_environment(
            {
                "DSM_DATABASE_DRIVER": "mariadb",
                "DSM_DATABASE_HOST": "db.internal",
                "DSM_DATABASE_USER": "dsm",
            }
        )

        self.assertEqual(config.driver, "mysql")
        self.assertEqual(config.port, 3306)

    def test_network_driver_requires_host(self):
        with self.assertRaisesRegex(
            DatabaseConfigurationError,
            "DSM_DATABASE_HOST",
        ):
            database_config_from_environment(
                {
                    "DSM_DATABASE_DRIVER": "mysql",
                    "DSM_DATABASE_USER": "dsm",
                }
            )

    def test_network_driver_requires_user(self):
        with self.assertRaisesRegex(
            DatabaseConfigurationError,
            "DSM_DATABASE_USER",
        ):
            database_config_from_environment(
                {
                    "DSM_DATABASE_DRIVER": "postgresql",
                    "DSM_DATABASE_HOST": "db.internal",
                }
            )

    def test_invalid_port_is_rejected(self):
        for value in ("not-a-number", "0", "65536"):
            with self.subTest(value=value):
                with self.assertRaises(
                    DatabaseConfigurationError
                ):
                    database_config_from_environment(
                        {
                            "DSM_DATABASE_DRIVER": "mysql",
                            "DSM_DATABASE_HOST": "db.internal",
                            "DSM_DATABASE_PORT": value,
                            "DSM_DATABASE_USER": "dsm",
                        }
                    )

    def test_backend_is_created_from_runtime_config(self):
        sentinel = object()

        with patch(
            "runtime_backend.create_backend",
            return_value=sentinel,
        ) as create_backend:
            result = backend_from_environment(
                {
                    "DSM_DATABASE_DRIVER": "sqlite",
                    "DSM_DATABASE": "capivara.db",
                }
            )

        self.assertIs(result, sentinel)
        config = create_backend.call_args.args[0]
        self.assertEqual(config.driver, "sqlite")
        self.assertTrue(
            config.database.endswith("capivara.db")
        )


if __name__ == "__main__":
    unittest.main()
