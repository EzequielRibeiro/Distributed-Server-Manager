#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"
for path in (DASHBOARD, DATABASE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from instance_provisioning_projection import dashboard_provision_state


class ProvisioningFailureProgressTest(unittest.TestCase):
    def test_failed_progress_never_looks_complete(self):
        state = dashboard_provision_state(
            {
                "provisioning_id": "instance-provision-test",
                "status": "failed",
                "current_step": "initial_reconcile",
                "progress": 100,
                "last_error": "runtime failed to start",
                "result": {},
            }
        )

        self.assertEqual("failed", state["status"])
        self.assertEqual("initial_reconcile", state["stage"])
        self.assertEqual(99, state["progress"])
        self.assertIn("Não foi possível", state["message"])
        self.assertEqual("runtime failed to start", state["error"])

    def test_completed_is_the_only_terminal_projection_at_100(self):
        state = dashboard_provision_state(
            {
                "status": "completed",
                "current_step": "completed",
                "progress": 100,
                "result": {"observed_state": "running"},
            }
        )

        self.assertEqual("running", state["status"])
        self.assertEqual(100, state["progress"])

    def test_running_progress_is_already_bounded_below_100(self):
        state = dashboard_provision_state(
            {
                "status": "running",
                "current_step": "materialize_runtime",
                "progress": 100,
                "result": {},
            }
        )

        self.assertEqual("provisioning", state["status"])
        self.assertEqual(99, state["progress"])

    def test_steam_auth_remains_a_distinct_pending_state(self):
        state = dashboard_provision_state(
            {
                "status": "failed",
                "current_step": "install_content",
                "progress": 100,
                "last_error": "Steam Guard required",
                "result": {"steam_auth_required": True},
            }
        )

        self.assertEqual("pending_steam_auth", state["status"])
        self.assertEqual(35, state["progress"])


if __name__ == "__main__":
    unittest.main()
