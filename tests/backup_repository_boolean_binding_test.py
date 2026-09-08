#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

for path in (
    ROOT,
    ROOT / "core",
    ROOT / "database",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import backup_repository
from backup_repository import BackupRepository


class FakeBackend:
    name = "postgresql"

    @contextmanager
    def transaction(self):
        yield object()


class FakeSession:
    calls = []

    def __init__(self, backend, connection):
        self.backend = backend
        self.connection = connection

    def execute(self, sql, parameters=()):
        self.__class__.calls.append(
            (str(sql), tuple(parameters))
        )
        return self

    def close(self):
        pass


class BackupRepositoryBooleanBindingTest(unittest.TestCase):
    def setUp(self):
        FakeSession.calls = []

    def _exercise(self, enabled: bool):
        repo = BackupRepository(FakeBackend())

        repo._instance = lambda iid: {
            "id": iid,
            "agent_id": "agent-1",
        }

        repo.get_policy = lambda iid: None

        with mock.patch.object(
            backup_repository,
            "AlertSession",
            FakeSession,
        ):
            result = repo.put_policy(
                {
                    "instance_id": "instance-1",
                    "enabled": enabled,
                },
                requested_by="test",
            )

        self.assertTrue(result["changed"])

        policy_insert = next(
            params
            for sql, params in FakeSession.calls
            if sql.startswith(
                "INSERT INTO backup_policies("
            )
        )

        revision_insert = next(
            params
            for sql, params in FakeSession.calls
            if sql.startswith(
                "INSERT INTO backup_policy_revisions("
            )
        )

        # backup_policies:
        # policy_id, instance_id, agent_id, enabled, ...
        policy_enabled = policy_insert[3]

        # backup_policy_revisions:
        # policy_id, revision, enabled, ...
        revision_enabled = revision_insert[2]

        self.assertIs(type(policy_enabled), bool)
        self.assertIs(type(revision_enabled), bool)

        self.assertIs(policy_enabled, enabled)
        self.assertIs(revision_enabled, enabled)

    def test_true_is_bound_as_python_bool(self):
        self._exercise(True)

    def test_false_is_bound_as_python_bool(self):
        self._exercise(False)

    def test_source_does_not_convert_enabled_to_integer(self):
        source = (
            ROOT / "database" / "backup_repository.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            '1 if item["enabled"] else 0',
            source,
        )

        self.assertGreaterEqual(
            source.count('bool(item["enabled"])'),
            2,
        )


if __name__ == "__main__":
    unittest.main()
