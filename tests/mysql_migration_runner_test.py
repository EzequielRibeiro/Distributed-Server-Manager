#!/usr/bin/env python3

from __future__ import annotations

import hashlib
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


from backend import (
    DatabaseMigrationError,
)

import mysql_engine


class FakeCursor:

    def __init__(
        self,
        connection,
        *,
        dictionary=False,
    ):
        self.connection = connection
        self.dictionary = dictionary
        self.query = ""
        self.closed = False
        self.nextsets = []

    def execute(
        self,
        sql,
        parameters=None,
    ):
        self.query = " ".join(
            sql.split()
        )

        self.connection.executed.append(
            (
                sql,
                parameters,
            )
        )

        if (
            self.connection.fail_on
            and self.connection.fail_on in sql
        ):
            raise RuntimeError(
                "forced SQL failure"
            )

        if (
            "CREATE TABLE IF NOT EXISTS "
            "schema_migrations"
            in self.query
        ):
            self.connection.schema_exists = True

        if (
            "INSERT INTO schema_migrations"
            in self.query
        ):
            version, name, checksum = parameters

            self.connection.applied[
                int(version)
            ] = {
                "version": int(version),
                "name": name,
                "checksum": checksum,
                "applied_at": None,
            }

    def fetchone(self):
        if (
            "information_schema.tables"
            in self.query
        ):
            return {
                "table_count": (
                    1
                    if self.connection.schema_exists
                    else 0
                )
            }

        if (
            "DATABASE() AS database_name"
            in self.query
        ):
            return {
                "database_name": "capivara",
                "user_name": "capivara@localhost",
                "server_version": "8.4.0",
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
                dict(row)
                for _, row
                in sorted(
                    self.connection.applied.items()
                )
            ]

        return []

    def nextset(self):
        if self.nextsets:
            return self.nextsets.pop(0)

        return None

    def close(self):
        self.closed = True


class FakeConnection:

    def __init__(self):
        self.schema_exists = False
        self.applied = {}
        self.executed = []
        self.fail_on = None
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(
        self,
        **kwargs,
    ):
        return FakeCursor(
            self,
            dictionary=kwargs.get(
                "dictionary",
                False,
            ),
        )

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class MySQLMigrationRunnerTest(
    unittest.TestCase
):

    def make_migration(
        self,
        directory: Path,
        version: int,
        name: str,
        sql: str,
    ):
        path = (
            directory
            / f"{version:03d}_{name}.sql"
        )

        path.write_text(
            sql,
            encoding="utf-8",
        )

        return mysql_engine.Migration(
            version=version,
            name=name,
            path=path,
            sql=sql,
            checksum=hashlib.sha256(
                sql.encode("utf-8")
            ).hexdigest(),
        )

    def test_applied_migrations_creates_tracking_table(self):
        connection = FakeConnection()

        result = (
            mysql_engine.applied_migrations(
                connection
            )
        )

        self.assertEqual(
            result,
            {},
        )

        self.assertTrue(
            connection.schema_exists
        )

    def test_apply_one_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            migration = self.make_migration(
                Path(temp),
                1,
                "initial",
                "CREATE TABLE example(id INTEGER);",
            )

            connection = FakeConnection()

            result = (
                mysql_engine.apply_migrations(
                    connection,
                    [migration],
                )
            )

            self.assertEqual(
                result,
                [1],
            )

            self.assertIn(
                1,
                connection.applied,
            )

            self.assertEqual(
                connection.commits,
                1,
            )

    def test_applied_migration_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            migration = self.make_migration(
                Path(temp),
                1,
                "initial",
                "SELECT 1;",
            )

            connection = FakeConnection()

            connection.applied[1] = {
                "version": 1,
                "name": "initial",
                "checksum": migration.checksum,
                "applied_at": None,
            }

            result = (
                mysql_engine.apply_migrations(
                    connection,
                    [migration],
                )
            )

            self.assertEqual(
                result,
                [],
            )

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            migration = self.make_migration(
                Path(temp),
                1,
                "initial",
                "SELECT 1;",
            )

            connection = FakeConnection()

            connection.applied[1] = {
                "version": 1,
                "name": "initial",
                "checksum": "0" * 64,
                "applied_at": None,
            }

            with self.assertRaisesRegex(
                DatabaseMigrationError,
                "checksum does not match",
            ):
                mysql_engine.apply_migrations(
                    connection,
                    [migration],
                )

    def test_failure_is_reported_and_rolls_back_dml(self):
        with tempfile.TemporaryDirectory() as temp:
            migration = self.make_migration(
                Path(temp),
                1,
                "broken",
                "BROKEN SQL;",
            )

            connection = FakeConnection()
            connection.fail_on = "BROKEN"

            with self.assertRaisesRegex(
                DatabaseMigrationError,
                "forced SQL failure",
            ):
                mysql_engine.apply_migrations(
                    connection,
                    [migration],
                )

            self.assertEqual(
                connection.rollbacks,
                1,
            )

            self.assertNotIn(
                1,
                connection.applied,
            )

    def test_multiple_migrations_apply_in_order(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)

            first = self.make_migration(
                directory,
                1,
                "initial",
                "SELECT 1;",
            )

            second = self.make_migration(
                directory,
                2,
                "second",
                "SELECT 2;",
            )

            connection = FakeConnection()

            result = (
                mysql_engine.apply_migrations(
                    connection,
                    [
                        first,
                        second,
                    ],
                )
            )

            self.assertEqual(
                result,
                [1, 2],
            )

            self.assertEqual(
                list(connection.applied),
                [1, 2],
            )

            self.assertEqual(
                connection.commits,
                2,
            )

    def test_server_flavor_mysql(self):
        self.assertEqual(
            mysql_engine.detect_server_flavor(
                "8.4.0"
            ),
            "mysql",
        )

    def test_server_flavor_mariadb(self):
        self.assertEqual(
            mysql_engine.detect_server_flavor(
                "11.8.3-MariaDB"
            ),
            "mariadb",
        )


if __name__ == "__main__":
    unittest.main()
