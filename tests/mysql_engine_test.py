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

import mysql_engine


class FakeCursor:
    def __init__(
        self,
        cipher="TLS_AES_256_GCM_SHA384",
    ):
        self.cipher = cipher
        self.closed = False
        self.executed = []

    def execute(
        self,
        sql,
        parameters=None,
    ):
        self.executed.append(
            (
                sql,
                parameters,
            )
        )

    def fetchone(self):
        return {
            "Variable_name": "Ssl_cipher",
            "Value": self.cipher,
        }

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(
        self,
        *,
        cipher="TLS_AES_256_GCM_SHA384",
    ):
        self.cipher = cipher
        self.closed = False
        self.cursor_calls = []

    def cursor(
        self,
        **kwargs,
    ):
        self.cursor_calls.append(
            kwargs
        )

        return FakeCursor(
            self.cipher
        )

    def close(self):
        self.closed = True


class FakeConnector:
    def __init__(
        self,
        connection=None,
    ):
        self.connection = (
            connection
            or FakeConnection()
        )

        self.calls = []

    def connect(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        return self.connection


class MySQLEngineTest(
    unittest.TestCase
):

    def base_config(
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

    def test_tls_aliases(self):
        self.assertEqual(
            mysql_engine.normalize_tls_mode(
                "prefer"
            ),
            "preferred",
        )

        self.assertEqual(
            mysql_engine.normalize_tls_mode(
                "require"
            ),
            "required",
        )

        self.assertEqual(
            mysql_engine.normalize_tls_mode(
                "verify_identity"
            ),
            "verify-full",
        )

    def test_invalid_tls_mode_is_rejected(self):
        with self.assertRaises(
            DatabaseConfigurationError
        ):
            mysql_engine.normalize_tls_mode(
                "magic"
            )

    def test_mariadb_driver_is_accepted(self):
        mysql_engine.validate_config(
            self.base_config(
                driver="mariadb"
            )
        )

    def test_invalid_driver_is_rejected(self):
        with self.assertRaises(
            DatabaseConfigurationError
        ):
            mysql_engine.validate_config(
                self.base_config(
                    driver="postgresql"
                )
            )

    def test_invalid_port_is_rejected(self):
        with self.assertRaises(
            DatabaseConfigurationError
        ):
            mysql_engine.validate_config(
                self.base_config(
                    port=70000
                )
            )

    def test_invalid_timeout_is_rejected(self):
        with self.assertRaises(
            DatabaseConfigurationError
        ):
            mysql_engine.validate_config(
                self.base_config(
                    connect_timeout=0
                )
            )

    def test_password_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = (
                Path(temp)
                / "password"
            )

            path.write_text(
                "secret-value\n",
                encoding="utf-8",
            )

            self.assertEqual(
                mysql_engine.read_password_file(
                    str(path)
                ),
                "secret-value",
            )

    def test_missing_password_file_is_rejected(self):
        with self.assertRaises(
            DatabaseConfigurationError
        ):
            mysql_engine.read_password_file(
                "does-not-exist.secret"
            )

    def test_disable_tls_parameters(self):
        result = (
            mysql_engine.tls_parameters(
                self.base_config(
                    tls_mode="disable"
                )
            )
        )

        self.assertEqual(
            result,
            {
                "ssl_disabled": True,
            },
        )

    def test_preferred_tls_parameters(self):
        result = (
            mysql_engine.tls_parameters(
                self.base_config(
                    tls_mode="preferred"
                )
            )
        )

        self.assertEqual(
            result,
            {
                "ssl_disabled": False,
            },
        )

    def test_verify_full_requires_ca(self):
        with patch.dict(
            mysql_engine.os.environ,
            {},
            clear=True,
        ):
            with self.assertRaises(
                DatabaseConfigurationError
            ):
                mysql_engine.tls_parameters(
                    self.base_config(
                        tls_mode="verify-full"
                    )
                )

    def test_verify_full_tls_parameters(self):
        with tempfile.TemporaryDirectory() as temp:
            ca_file = (
                Path(temp)
                / "ca.pem"
            )

            ca_file.write_text(
                "test-ca",
                encoding="utf-8",
            )

            with patch.dict(
                mysql_engine.os.environ,
                {
                    "DSM_DATABASE_TLS_CA":
                    str(ca_file),
                },
                clear=True,
            ):
                result = (
                    mysql_engine.tls_parameters(
                        self.base_config(
                            tls_mode="verify-full"
                        )
                    )
                )

        self.assertFalse(
            result["ssl_disabled"]
        )

        self.assertTrue(
            result["ssl_verify_cert"]
        )

        self.assertTrue(
            result["ssl_verify_identity"]
        )

    def test_connection_parameters(self):
        parameters = (
            mysql_engine.connection_parameters(
                self.base_config()
            )
        )

        self.assertEqual(
            parameters["host"],
            "db.internal",
        )

        self.assertEqual(
            parameters["port"],
            3306,
        )

        self.assertEqual(
            parameters["database"],
            "capivara",
        )

        self.assertEqual(
            parameters["user"],
            "capivara",
        )

        self.assertEqual(
            parameters["connection_timeout"],
            5,
        )

        self.assertFalse(
            parameters["autocommit"]
        )

        self.assertFalse(
            parameters["ssl_disabled"]
        )

        self.assertNotIn(
            "password",
            parameters,
        )

    def test_connector_is_optional_until_used(self):
        original = (
            mysql_engine.importlib.import_module
        )

        def fake_import(name):
            if name == "mysql.connector":
                raise ModuleNotFoundError(
                    "mysql.connector"
                )

            return original(name)

        with patch.object(
            mysql_engine.importlib,
            "import_module",
            side_effect=fake_import,
        ):
            with self.assertRaisesRegex(
                DatabaseConfigurationError,
                "mysql-connector-python",
            ):
                mysql_engine._load_mysql_connector()

    def test_connect_uses_safe_parameters(self):
        connection = FakeConnection()
        connector = FakeConnector(
            connection
        )

        with patch.object(
            mysql_engine,
            "_load_mysql_connector",
            return_value=connector,
        ):
            result = mysql_engine.connect(
                self.base_config(
                    tls_mode="disable"
                )
            )

        self.assertIs(
            result,
            connection,
        )

        self.assertEqual(
            len(connector.calls),
            1,
        )

        call = connector.calls[0]

        self.assertEqual(
            call["database"],
            "capivara",
        )

        self.assertEqual(
            call["connection_timeout"],
            5,
        )

        self.assertTrue(
            call["ssl_disabled"]
        )

    def test_required_tls_accepts_encrypted_connection(self):
        connection = FakeConnection(
            cipher="TLS_AES_256_GCM_SHA384"
        )

        connector = FakeConnector(
            connection
        )

        with patch.object(
            mysql_engine,
            "_load_mysql_connector",
            return_value=connector,
        ):
            result = mysql_engine.connect(
                self.base_config(
                    tls_mode="required"
                )
            )

        self.assertIs(
            result,
            connection,
        )

        self.assertEqual(
            connection.cursor_calls,
            [
                {
                    "dictionary": True,
                }
            ],
        )

    def test_required_tls_rejects_unencrypted_connection(self):
        connection = FakeConnection(
            cipher=""
        )

        connector = FakeConnector(
            connection
        )

        with patch.object(
            mysql_engine,
            "_load_mysql_connector",
            return_value=connector,
        ):
            with self.assertRaisesRegex(
                DatabaseConnectionError,
                "not encrypted",
            ):
                mysql_engine.connect(
                    self.base_config(
                        tls_mode="required"
                    )
                )

        self.assertTrue(
            connection.closed
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
                mysql_engine.load_migrations(
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

            self.assertEqual(
                migrations[0].checksum,
                hashlib.sha256(
                    b"SELECT 1;\n"
                ).hexdigest(),
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
                mysql_engine.load_migrations(
                    directory
                )


if __name__ == "__main__":
    unittest.main()
