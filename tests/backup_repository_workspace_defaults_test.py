#!/usr/bin/env python3

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"

if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from backup_repository import BackupRepository
from instance_backup_policy_defaults import (
    default_instance_backup_policy,
)


class Cursor:
    def __init__(self, *, row=None, rows=None):
        self.row = row
        self.rows = (
            list(rows)
            if rows is not None
            else ([] if row is None else [row])
        )

    def fetchone(self):
        return self.row

    def fetchall(self):
        return list(self.rows)


class Connection:
    def __init__(
        self,
        *,
        schedule_exists=False,
        concurrent_schedule_winner=False,
    ):
        self.schedule_exists = schedule_exists
        self.concurrent_schedule_winner = (
            concurrent_schedule_winner
        )
        self.insert_attempts = []

    def execute(self, sql, parameters=()):
        normalized = " ".join(str(sql).split())

        if (
            "SELECT i.id AS instance_id" in normalized
            and
            "LEFT JOIN instance_backup_policy" in normalized
        ):
            return Cursor(
                rows=[
                    {
                        "instance_id": "instance-1",
                        "workspace_instance_id": (
                            "instance-1"
                            if self.schedule_exists
                            else None
                        ),
                    }
                ]
            )

        if normalized.startswith(
            "INSERT INTO instance_backup_policy"
        ):
            self.insert_attempts.append(tuple(parameters))

            if self.concurrent_schedule_winner:
                self.concurrent_schedule_winner = False
                self.schedule_exists = True
                raise RuntimeError(
                    "simulated concurrent UNIQUE winner"
                )

            self.schedule_exists = True
            return Cursor()

        if (
            "SELECT enabled,schedule_time,"
            "schedule_timezone,healthy_only,"
            "keep_single_operational "
            "FROM instance_backup_policy"
            in normalized
        ):
            if not self.schedule_exists:
                return Cursor(row=None)

            return Cursor(
                row={
                    "enabled": True,
                    "schedule_time": "04:00",
                    "schedule_timezone": "UTC",
                    "healthy_only": True,
                    "keep_single_operational": True,
                }
            )

        raise AssertionError(
            f"unexpected SQL in fake backend: {normalized}"
        )


class Backend:
    name = "sqlite"

    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection

    @contextmanager
    def transaction(self):
        yield self.connection


class WorkspaceDefaultReconciliationTest(unittest.TestCase):
    def repository(self, connection):
        repository = BackupRepository(
            Backend(connection)
        )

        policy_calls = []

        repository.get_policy = (
            lambda instance_id: None
        )

        def put_policy(raw, *, requested_by=None):
            policy_calls.append(
                (dict(raw), requested_by)
            )
            return {
                "policy": {
                    "instance_id": raw["instance_id"]
                },
                "changed": True,
            }

        repository.put_policy = put_policy

        return repository, policy_calls

    def test_shared_default_contract(self):
        value = default_instance_backup_policy(
            "instance-1"
        )

        self.assertEqual(
            value,
            {
                "instance_id": "instance-1",
                "enabled": True,
                "schedule_time": "04:00",
                "schedule_timezone": "UTC",
                "healthy_only": True,
                "keep_single_operational": True,
            },
        )

    def test_missing_workspace_schedule_is_materialized(self):
        connection = Connection(
            schedule_exists=False
        )
        repository, policy_calls = self.repository(
            connection
        )

        created = repository._ensure_workspace_policies(
            "agent-1"
        )

        self.assertEqual(created, 1)
        self.assertTrue(connection.schedule_exists)

        self.assertEqual(
            connection.insert_attempts,
            [
                (
                    "instance-1",
                    True,
                    "04:00",
                    "UTC",
                    True,
                    True,
                )
            ],
        )

        self.assertEqual(
            policy_calls,
            [
                (
                    {"instance_id": "instance-1"},
                    "scheduler",
                )
            ],
        )

    def test_existing_canonical_policy_preserves_legacy_interval_mode(self):
        connection = Connection(
            schedule_exists=False
        )

        repository = BackupRepository(
            Backend(connection)
        )

        existing = {
            "instance_id": "instance-1",
            "enabled": True,
            "interval_seconds": 600,
        }

        repository.get_policy = (
            lambda instance_id: existing
        )

        put_calls = []

        def put_policy(raw, *, requested_by=None):
            put_calls.append(
                (dict(raw), requested_by)
            )
            raise AssertionError(
                "existing canonical policy must not be recreated"
            )

        repository.put_policy = put_policy

        created = repository._ensure_workspace_policies(
            "agent-1"
        )

        self.assertEqual(created, 0)
        self.assertEqual(
            connection.insert_attempts,
            [],
        )
        self.assertEqual(put_calls, [])
        self.assertFalse(connection.schedule_exists)


    def test_existing_workspace_schedule_is_not_overwritten(self):
        connection = Connection(
            schedule_exists=True
        )
        repository, policy_calls = self.repository(
            connection
        )

        created = repository._ensure_workspace_policies(
            "agent-1"
        )

        self.assertEqual(created, 1)
        self.assertEqual(
            connection.insert_attempts,
            [],
        )
        self.assertEqual(len(policy_calls), 1)

    def test_workspace_insert_does_not_hide_real_database_failure(self):
        class BrokenConnection(Connection):
            def execute(self, sql, parameters=()):
                normalized = " ".join(str(sql).split())

                if normalized.startswith(
                    "INSERT INTO instance_backup_policy"
                ):
                    raise RuntimeError(
                        "simulated real database failure"
                    )

                return super().execute(sql, parameters)

        connection = BrokenConnection(
            schedule_exists=False
        )

        repository, policy_calls = self.repository(
            connection
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "simulated real database failure",
        ):
            repository._ensure_workspace_policies(
                "agent-1"
            )

        self.assertEqual(policy_calls, [])


    def test_concurrent_workspace_insert_is_tolerated(self):
        connection = Connection(
            schedule_exists=False,
            concurrent_schedule_winner=True,
        )
        repository, policy_calls = self.repository(
            connection
        )

        created = repository._ensure_workspace_policies(
            "agent-1"
        )

        self.assertEqual(created, 1)
        self.assertTrue(connection.schedule_exists)
        self.assertEqual(len(policy_calls), 1)


if __name__ == "__main__":
    unittest.main()
