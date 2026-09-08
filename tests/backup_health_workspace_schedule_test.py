#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for path in (
    ROOT,
    ROOT / "core",
    ROOT / "database",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backup_intelligence import evaluate_policy


class BackupHealthWorkspaceScheduleTest(
    unittest.TestCase
):
    def policy(self):
        return {
            "instance_id": "instance-1",
            "agent_id": "agent-1",
            "policy_id": "policy-1",
            "revision": 1,
            "enabled": True,
            "interval_seconds": 21600,
            "created_at": "2026-09-07T20:00:00Z",
        }

    def completed_job(self):
        return {
            "action": "create",
            "status": "completed",
            "backup_id": "backup-1",
            "completed_at": "2026-09-07T21:02:17Z",
        }

    def workspace(self, enabled=True):
        return {
            "enabled": enabled,
            "schedule_time": "04:00",
            "schedule_timezone": "UTC",
            "healthy_only": True,
            "keep_single_operational": True,
        }

    def test_workspace_uses_next_daily_schedule(
        self,
    ):
        result = evaluate_policy(
            self.policy(),
            [self.completed_job()],
            now=datetime(
                2026, 9, 7, 23, 16,
                tzinfo=timezone.utc,
            ),
            schedule=self.workspace(),
        )

        self.assertEqual(
            result["schedule_source"],
            "workspace",
        )
        self.assertEqual(
            result["next_due_at"],
            "2026-09-08T04:00:00Z",
        )
        self.assertEqual(
            result["seconds_until_due"],
            17040,
        )
        self.assertEqual(
            result["health"],
            "healthy",
        )

    def test_legacy_without_workspace_uses_interval(
        self,
    ):
        result = evaluate_policy(
            self.policy(),
            [self.completed_job()],
            now=datetime(
                2026, 9, 7, 23, 16,
                tzinfo=timezone.utc,
            ),
        )

        self.assertEqual(
            result["schedule_source"],
            "interval",
        )
        self.assertEqual(
            result["next_due_at"],
            "2026-09-08T03:02:17Z",
        )

    def test_workspace_disabled_is_effectively_disabled(
        self,
    ):
        result = evaluate_policy(
            self.policy(),
            [self.completed_job()],
            now=datetime(
                2026, 9, 7, 23, 16,
                tzinfo=timezone.utc,
            ),
            schedule=self.workspace(False),
        )

        self.assertFalse(result["enabled"])
        self.assertTrue(
            result["canonical_enabled"]
        )
        self.assertFalse(
            result["workspace_enabled"]
        )
        self.assertEqual(
            result["health"],
            "disabled",
        )

    def test_workspace_due_after_schedule_without_today_backup(
        self,
    ):
        previous = dict(self.completed_job())
        previous["completed_at"] = (
            "2026-09-06T21:02:17Z"
        )

        result = evaluate_policy(
            self.policy(),
            [previous],
            now=datetime(
                2026, 9, 7, 5, 0,
                tzinfo=timezone.utc,
            ),
            schedule=self.workspace(),
        )

        self.assertEqual(
            result["next_due_at"],
            "2026-09-07T04:00:00Z",
        )
        self.assertEqual(
            result["seconds_until_due"],
            -3600,
        )
        self.assertEqual(
            result["health"],
            "due",
        )

    def test_workspace_before_schedule_without_backup_is_never_run(
        self,
    ):
        result = evaluate_policy(
            self.policy(),
            [],
            now=datetime(
                2026, 9, 7, 3, 0,
                tzinfo=timezone.utc,
            ),
            schedule=self.workspace(),
        )

        self.assertEqual(
            result["next_due_at"],
            "2026-09-07T04:00:00Z",
        )
        self.assertEqual(
            result["health"],
            "never_run",
        )


if __name__ == "__main__":
    unittest.main()
