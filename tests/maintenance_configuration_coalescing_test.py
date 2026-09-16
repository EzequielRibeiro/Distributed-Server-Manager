#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from maintenance_configuration_coordinator import (
    MaintenanceConfigurationCoordinator,
    SERVER_SETTINGS_NAMESPACE,
)


class _Configuration:
    def __init__(self, *, restart_required=True, updated_at="2026-09-16T12:00:00Z"):
        self.raw = {
            "namespace": SERVER_SETTINGS_NAMESPACE,
            "updated_at": updated_at,
            "value": {
                "settings": {"hostname": "Capivara"},
                "declaration": {"restart_required": restart_required},
            },
        }
        self.resolved = {
            "namespace": SERVER_SETTINGS_NAMESPACE,
            "revision": "resolved-abc123",
            "checksum": "checksum-abc123",
            "value": self.raw["value"],
        }

    def get(self, **kwargs):
        return dict(self.raw)

    def resolve_for_instance(self, agent_id, instance_id):
        return [dict(self.resolved)]


class _Coordinator(MaintenanceConfigurationCoordinator):
    def __init__(self, *, restart_required=True, last_success=None, state=None):
        self.configuration = _Configuration(restart_required=restart_required)
        self._success = last_success
        self._state = state

    def _instance_agent(self, instance_id):
        return "agent-1"

    def _last_successful_restart(self, instance_id):
        return self._success

    def _agent_state(self, agent_id, instance_id):
        return dict(self._state) if isinstance(self._state, dict) else None


class MaintenanceConfigurationCoalescingTest(unittest.TestCase):
    def test_restart_required_revision_after_last_success_is_discovered(self):
        coordinator = _Coordinator(
            last_success=datetime(2026, 9, 16, 11, 0, tzinfo=timezone.utc)
        )
        work = coordinator.discover("instance-1")
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["kind"], "configuration")
        self.assertEqual(work[0]["ref"], SERVER_SETTINGS_NAMESPACE)
        self.assertEqual(work[0]["available_version"], "resolved-abc123")

    def test_successful_restart_after_configuration_clears_pending_work(self):
        coordinator = _Coordinator(
            last_success=datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(coordinator.discover("instance-1"), [])

    def test_hot_apply_declaration_never_enters_restart_window(self):
        coordinator = _Coordinator(restart_required=False)
        self.assertEqual(coordinator.discover("instance-1"), [])

    def test_alignment_waits_for_exact_resolved_revision_and_checksum(self):
        coordinator = _Coordinator(
            state={
                "status": "applied",
                "desired_revision": "resolved-abc123",
                "applied_revision": "old-revision",
                "applied_checksum": "old-checksum",
            }
        )
        work = coordinator.discover("instance-1")
        view = coordinator.alignment("instance-1", work)
        self.assertFalse(view["ready"])
        self.assertEqual(view["pending"], [SERVER_SETTINGS_NAMESPACE])
        self.assertEqual(view["work"][0]["status"], "pending")

        coordinator._state = {
            "status": "applied",
            "desired_revision": "resolved-abc123",
            "applied_revision": "resolved-abc123",
            "applied_checksum": "checksum-abc123",
        }
        view = coordinator.alignment("instance-1", work)
        self.assertTrue(view["ready"])
        self.assertEqual(view["aligned"], [SERVER_SETTINGS_NAMESPACE])
        self.assertEqual(view["work"][0]["status"], "aligned")

    def test_failed_agent_reconciliation_fails_closed(self):
        coordinator = _Coordinator(
            state={
                "status": "failed",
                "desired_revision": "resolved-abc123",
                "applied_revision": None,
                "applied_checksum": None,
                "last_error": "materialization failed",
            }
        )
        view = coordinator.alignment("instance-1", coordinator.discover("instance-1"))
        self.assertFalse(view["ready"])
        self.assertEqual(len(view["failed"]), 1)
        self.assertEqual(view["failed"][0]["error"], "materialization failed")


if __name__ == "__main__":
    unittest.main()
