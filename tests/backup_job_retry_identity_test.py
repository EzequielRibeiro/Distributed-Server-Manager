#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT / "database", ROOT / "core"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import baseline_upgrade_engine as upgrades


class _Result:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        return None


class _PostgresConnection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if "information_schema.tables" in sql:
            return _Result([{"table_name": "backup_jobs"}])
        if "FROM pg_constraint c" in sql:
            return _Result(
                [
                    {
                        "conname": "backup_jobs_backup_id_key",
                        "columns": ["backup_id"],
                    },
                    {
                        "conname": "keep_unrelated_unique",
                        "columns": ["instance_id", "command_id"],
                    },
                ]
            )
        return _Result()


class _MySqlCursor:
    def __init__(self, connection, dictionary=False):
        self.connection = connection
        self.dictionary = dictionary
        self.rows = []

    def execute(self, sql, params=()):
        self.connection.statements.append((sql, params))
        if "information_schema.tables" in sql:
            self.rows = [{"table_name": "backup_jobs"}]
        elif "information_schema.STATISTICS" in sql:
            self.rows = [
                {
                    "index_name": "backup_id",
                    "non_unique": 0,
                    "columns_csv": "backup_id",
                },
                {
                    "index_name": "keep_unrelated_unique",
                    "non_unique": 0,
                    "columns_csv": "instance_id,command_id",
                },
            ]
        else:
            self.rows = []

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def close(self):
        return None


class _MySqlConnection:
    def __init__(self):
        self.statements = []

    def cursor(self, dictionary=False):
        return _MySqlCursor(self, dictionary=dictionary)


class BackupJobRetryIdentityTest(unittest.TestCase):
    def test_upgrade_registry_advances_to_retry_identity_v7(self):
        self.assertEqual(upgrades.latest_upgrade_version(), 7)
        self.assertEqual(upgrades.UPGRADES[-1].name, "backup_job_retry_identity")

    def test_sqlite_allows_multiple_jobs_for_same_backup_artifact(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE backup_jobs ("
            "command_id TEXT PRIMARY KEY, backup_id TEXT, action TEXT, status TEXT)"
        )
        backend = SimpleNamespace(name="sqlite")

        upgrades._upgrade_backup_job_retry_identity(backend, connection)
        upgrades._upgrade_backup_job_retry_identity(backend, connection)

        connection.execute(
            "INSERT INTO backup_jobs(command_id,backup_id,action,status) "
            "VALUES ('job-1','artifact-1','restore','failed')"
        )
        connection.execute(
            "INSERT INTO backup_jobs(command_id,backup_id,action,status) "
            "VALUES ('job-2','artifact-1','restore','pending')"
        )

        rows = connection.execute(
            "SELECT command_id FROM backup_jobs WHERE backup_id='artifact-1' "
            "ORDER BY command_id"
        ).fetchall()
        self.assertEqual([row["command_id"] for row in rows], ["job-1", "job-2"])

        indexes = connection.execute("PRAGMA index_list('backup_jobs')").fetchall()
        retry_index = next(
            row for row in indexes if row["name"] == "idx_backup_jobs_backup_id"
        )
        self.assertEqual(int(retry_index["unique"]), 0)
        connection.close()

    def test_postgresql_drops_only_standalone_backup_id_unique_constraint(self):
        connection = _PostgresConnection()
        backend = SimpleNamespace(name="postgresql")

        upgrades._upgrade_backup_job_retry_identity(backend, connection)

        sql = "\n".join(statement for statement, _ in connection.statements)
        self.assertIn(
            'ALTER TABLE public.backup_jobs DROP CONSTRAINT "backup_jobs_backup_id_key"',
            sql,
        )
        self.assertNotIn(
            'DROP CONSTRAINT "keep_unrelated_unique"',
            sql,
        )
        self.assertIn(
            "CREATE INDEX IF NOT EXISTS idx_backup_jobs_backup_id "
            "ON public.backup_jobs(backup_id)",
            sql,
        )

    def test_mysql_drops_only_standalone_backup_id_unique_index(self):
        connection = _MySqlConnection()
        backend = SimpleNamespace(name="mysql")

        upgrades._upgrade_backup_job_retry_identity(backend, connection)

        sql = "\n".join(statement for statement, _ in connection.statements)
        self.assertIn("ALTER TABLE backup_jobs DROP INDEX `backup_id`", sql)
        self.assertNotIn("DROP INDEX `keep_unrelated_unique`", sql)
        self.assertIn(
            "CREATE INDEX idx_backup_jobs_backup_id ON backup_jobs(backup_id)",
            sql,
        )


if __name__ == "__main__":
    unittest.main()
