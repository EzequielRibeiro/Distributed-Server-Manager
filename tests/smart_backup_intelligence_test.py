#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from core.backup_intelligence import aggregate_health, apply_preset, evaluate_policy, preset_names


class SmartBackupIntelligenceTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        self.policy = {
            "policy_id": "p-1",
            "instance_id": "instance-1",
            "agent_id": "agent-1",
            "revision": 3,
            "enabled": True,
            "interval_seconds": 3600,
            "created_at": (self.now - timedelta(days=1)).isoformat(),
        }

    def job(self, status, minutes_ago, **extra):
        when = (self.now - timedelta(minutes=minutes_ago)).isoformat()
        return {
            "action": "create",
            "status": status,
            "created_at": when,
            "updated_at": when,
            "completed_at": when if status in {"completed", "failed"} else None,
            **extra,
        }

    def test_presets_are_canonical_policy_inputs(self):
        self.assertEqual(["balanced", "config-safe", "daily", "frequent"], preset_names())
        value = apply_preset("instance-1", "balanced")
        self.assertEqual("instance-1", value["instance_id"])
        self.assertEqual(21600, value["interval_seconds"])
        self.assertEqual(14, value["retention_count"])
        self.assertNotIn("description", value)

    def test_healthy_policy_reports_next_due(self):
        health = evaluate_policy(
            self.policy,
            [self.job("completed", 30, backup_id="b-1", size_bytes=123, sha256="abc")],
            now=self.now,
        )
        self.assertEqual("healthy", health["health"])
        self.assertEqual(1800, health["seconds_until_due"])
        self.assertEqual("b-1", health["last_backup_id"])
        self.assertEqual(100.0, health["success_rate_percent"])

    def test_due_and_overdue_are_distinct(self):
        due = evaluate_policy(self.policy, [self.job("completed", 61)], now=self.now)
        overdue = evaluate_policy(self.policy, [self.job("completed", 121)], now=self.now)
        self.assertEqual("due", due["health"])
        self.assertEqual("overdue", overdue["health"])

    def test_repeated_failures_degrade_policy(self):
        health = evaluate_policy(
            self.policy,
            [
                self.job("failed", 5, last_error="disk full"),
                self.job("failed", 15, last_error="disk full"),
                self.job("completed", 30),
            ],
            now=self.now,
        )
        self.assertEqual("degraded", health["health"])
        self.assertEqual(2, health["consecutive_failures"])
        self.assertEqual("disk full", health["last_error"])
        self.assertAlmostEqual(33.3, health["success_rate_percent"])

    def test_disabled_policy_is_not_an_alert(self):
        policy = dict(self.policy, enabled=False)
        health = evaluate_policy(policy, [], now=self.now)
        self.assertEqual("disabled", health["health"])
        fleet = aggregate_health([health])
        self.assertEqual(0, fleet["attention_required"])
        self.assertEqual({"disabled": 1}, fleet["counts"])

    def test_never_completed_old_policy_is_overdue(self):
        health = evaluate_policy(self.policy, [], now=self.now)
        self.assertEqual("overdue", health["health"])


if __name__ == "__main__":
    unittest.main()
