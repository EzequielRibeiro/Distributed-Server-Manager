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

import postgresql_engine


class FakeResult:

    def __init__(
        self,
        *,
        one=None,
        all_rows=None,
    ):
        self.one = one
        self.all_rows = all_rows or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.all_rows


class FakeTransaction:

    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transactions += 1
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        if exc_type is None:
            self.connection.commits += 1
        else:
            self.connection.rollbacks += 1

        return False


class FakeConnection:

    def __init__(self):
        self.transactions = 0
        self.commits = 0
        self.rollbacks = 0
        self.schema_exists = False
        self.applied = {}
        self.executed_sql = []
        self.fail_on = None

    def transaction(self):
        return FakeTransaction(self)

    def execute(
        self,
        sql,
        parameters=None,
    ):
        normalized = " ".join(
            sql.split()
        )

        self.executed_sql.append(
            (
                normalized,
                parameters,
            )
        )

        if (
            self.fail_on
            and self.fail_on in sql
        ):
            raise RuntimeError(
                "forced SQL failure"
            )

        if (
            "CREATE TABLE IF NOT EXISTS "
            "schema_migrations"
            in normalized
        ):
            self.schema_exists = True
            return FakeResult()

        if (
            "FROM schema_migrations"
            in normalized
        ):
            return FakeResult(
                all_rows=[
                    dict(value)
                    for _, value
                    in sorted(
                        self.applied.items()
                    )
                ]
            )

        if (
            "INSERT INTO schema_migrations"
            in normalized
        ):
            version, name, checksum = parameters

            self.applied[int(version)] = {
                "version": int(version),
                "name": name,
                "checksum": checksum,
                "applied_at": None,
            }

            return FakeResult()

        if (
            "information_schema.tables"
            in normalized
        ):
            return FakeResult(
                one={
                    "exists": self.schema_exists,
                }
            )

        if "current_setting" in normalized:
            return FakeResult(
                one={
                    "database": "capivara",
                    "user": "capivara",
                    "server_version": "17.0",
                }
            )

        if "SELECT 1 AS ok" in normalized:
            return FakeResult(
                one={
                    "ok": 1,
                    "database": "capivara",
                    "user": "capivara",
                }
            )

        return FakeResult()


class PostgreSQLMigrationRunnerTest(
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

        return postgresql_engine.Migration(
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
            postgresql_engine.applied_migrations(
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
            directory = Path(temp)

            migration = self.make_migration(
                directory,
                1,
                "initial",
                "CREATE TABLE example(id INTEGER);",
            )

            connection = FakeConnection()

            result = (
                postgresql_engine.apply_migrations(
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

    def test_applied_migration_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)

            migration = self.make_migration(
                directory,
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
                postgresql_engine.apply_migrations(
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
            directory = Path(temp)

            migration = self.make_migration(
                directory,
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
                postgresql_engine.apply_migrations(
                    connection,
                    [migration],
                )

    def test_failure_rolls_back_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)

            migration = self.make_migration(
                directory,
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
                postgresql_engine.apply_migrations(
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
                postgresql_engine.apply_migrations(
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


if __name__ == "__main__":
    unittest.main()
