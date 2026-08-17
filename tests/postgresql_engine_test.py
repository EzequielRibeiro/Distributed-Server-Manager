#!/usr/bin/env python3

from __future__ import annotations

import hashlib
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
    DatabaseConfigurationError,
    DatabaseConnectionError,
)

import postgresql_engine


class FakePsycopg:
    def __init__(self):
        self.calls = []
        self.connection = object()

    def connect(self, **kwargs):
        self.calls.append(kwargs)
        return self.connection


class PostgreSQLEngineTest(
    unittest.TestCase
):

    def base_config(
        self,
        **overrides,
    ) -> DatabaseConfig:

        values = {
            "driver": "postgresql",
            "database": "capivara",
            "host": "db.internal",
            "port": 5432,
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

    def test_sslmode_aliases(self):
        self.assertEqual(
            postgresql_engine.normalize_sslmode(
                "preferred"
            ),
            "prefer",
        )

        self.assertEqual(
            postgresql_engine.normalize_sslmode(
                "required"
            ),
            "require",
        )

    def test_native_sslmodes_are_preserved(self):
        for mode in (
            "disable",
            "allow",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        ):
            with self.subTest(mode=mode):
                self.assertEqual(
                    postgresql_engine.normalize_sslmode(
                        mode
                    ),
                    mode,
                )

    def test_invalid_sslmode_is_rejected(self):
        with self.assertRaises(
            DatabaseConfigurationError
        ):
            postgresql_engine.normalize_sslmode(
                "insecure-magic"
            )

    def test_invalid_driver_is_rejected(self):
        config = self.base_config(
            driver="sqlite"
        )

        with self.assertRaises(
            DatabaseConfigurationError
        ):
            postgresql_engine.validate_config(
                config
            )

    def test_missing_host_is_rejected(self):
        config = self.base_config(
            host=""
        )

        with self.assertRaises(
            DatabaseConfigurationError
        ):
            postgresql_engine.validate_config(
                config
            )

    def test_invalid_port_is_rejected(self):
        config = self.base_config(
            port=70000
        )

        with self.assertRaises(
            DatabaseConfigurationError
        ):
            postgresql_engine.validate_config(
                config
            )

    def test_invalid_timeout_is_rejected(self):
        config = self.base_config(
            connect_timeout=0
        )

        with self.assertRaises(
            DatabaseConfigurationError
        ):
            postgresql_engine.validate_config(
                config
            )

    def test_missing_password_file_is_rejected(self):
        with self.assertRaises(
            DatabaseConfigurationError
        ):
            postgresql_engine.read_password_file(
                "definitely-does-not-exist.secret"
            )

    def test_empty_password_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            password_file = (
                Path(temp)
                / "password"
            )

            password_file.write_text(
                "",
                encoding="utf-8",
            )

            with self.assertRaises(
                DatabaseConfigurationError
            ):
                postgresql_engine.read_password_file(
                    str(password_file)
                )

    def test_password_file_is_read_without_newline(self):
        with tempfile.TemporaryDirectory() as temp:
            password_file = (
                Path(temp)
                / "password"
            )

            password_file.write_text(
                "secret-value\n",
                encoding="utf-8",
            )

            self.assertEqual(
                postgresql_engine.read_password_file(
                    str(password_file)
                ),
                "secret-value",
            )

    def test_connection_parameters(self):
        config = self.base_config()

        parameters = (
            postgresql_engine.connection_parameters(
                config
            )
        )

        self.assertEqual(
            parameters,
            {
                "host": "db.internal",
                "port": 5432,
                "dbname": "capivara",
                "user": "capivara",
                "connect_timeout": 5,
                "sslmode": "prefer",
            },
        )

        self.assertNotIn(
            "password",
            parameters,
        )

    def test_connection_parameters_read_password_file(self):
        with tempfile.TemporaryDirectory() as temp:
            password_file = (
                Path(temp)
                / "password"
            )

            password_file.write_text(
                "super-secret\n",
                encoding="utf-8",
            )

            config = self.base_config(
                password_file=str(
                    password_file
                )
            )

            parameters = (
                postgresql_engine.connection_parameters(
                    config
                )
            )

            self.assertEqual(
                parameters["password"],
                "super-secret",
            )

    def test_psycopg_is_optional_until_used(self):
        original = (
            postgresql_engine.importlib.import_module
        )

        def fake_import(name):
            if name == "psycopg":
                raise ModuleNotFoundError(
                    "psycopg"
                )

            return original(name)

        with patch.object(
            postgresql_engine.importlib,
            "import_module",
            side_effect=fake_import,
        ):
            with self.assertRaisesRegex(
                DatabaseConfigurationError,
                "Psycopg 3",
            ):
                postgresql_engine._load_psycopg()

    def test_connect_uses_dict_row_and_safe_parameters(self):
        fake_psycopg = FakePsycopg()
        fake_dict_row = object()

        with patch.object(
            postgresql_engine,
            "_load_psycopg",
            return_value=(
                fake_psycopg,
                fake_dict_row,
            ),
        ):
            connection = (
                postgresql_engine.connect(
                    self.base_config()
                )
            )

        self.assertIs(
            connection,
            fake_psycopg.connection,
        )

        self.assertEqual(
            len(fake_psycopg.calls),
            1,
        )

        call = fake_psycopg.calls[0]

        self.assertEqual(
            call["host"],
            "db.internal",
        )

        self.assertEqual(
            call["port"],
            5432,
        )

        self.assertEqual(
            call["dbname"],
            "capivara",
        )

        self.assertEqual(
            call["user"],
            "capivara",
        )

        self.assertEqual(
            call["sslmode"],
            "prefer",
        )

        self.assertIs(
            call["row_factory"],
            fake_dict_row,
        )

    def test_connection_failure_is_wrapped(self):
        class FailingPsycopg:
            @staticmethod
            def connect(**kwargs):
                raise RuntimeError(
                    "connection refused"
                )

        with patch.object(
            postgresql_engine,
            "_load_psycopg",
            return_value=(
                FailingPsycopg(),
                object(),
            ),
        ):
            with self.assertRaisesRegex(
                DatabaseConnectionError,
                "connection refused",
            ):
                postgresql_engine.connect(
                    self.base_config()
                )

    def test_load_migrations(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)

            first = directory / "001_initial.sql"
            second = directory / "002_example.sql"

            first.write_text(
                "SELECT 1;\n",
                encoding="utf-8",
            )

            second.write_text(
                "SELECT 2;\n",
                encoding="utf-8",
            )

            migrations = (
                postgresql_engine.load_migrations(
                    directory
                )
            )

            self.assertEqual(
                [
                    migration.version
                    for migration in migrations
                ],
                [1, 2],
            )

            self.assertEqual(
                migrations[0].name,
                "initial",
            )

            expected_checksum = (
                hashlib.sha256(
                    b"SELECT 1;\n"
                ).hexdigest()
            )

            self.assertEqual(
                migrations[0].checksum,
                expected_checksum,
            )

    def test_invalid_migration_filename_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)

            (
                directory
                / "bad-name.sql"
            ).write_text(
                "SELECT 1;",
                encoding="utf-8",
            )

            with self.assertRaises(
                DatabaseConfigurationError
            ):
                postgresql_engine.load_migrations(
                    directory
                )


if __name__ == "__main__":
    unittest.main()
