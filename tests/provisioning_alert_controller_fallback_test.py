#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from alert_repository import AlertRepository
from tests.provisioning_failure_diagnostics_test import ControllerFailureDiagnosticsTest


class LegacyInstanceControllerFallbackTest(ControllerFailureDiagnosticsTest):
    """Reproduce legacy rows whose Controller binding only survives on Customer."""

    def _simulate_legacy_instance_without_controller(self) -> None:
        with self.backend.transaction() as conn:
            cur = conn.cursor()
            triggers = cur.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
            for trigger in triggers:
                sql = str(trigger["sql"] or "")
                if "instance_requires_controller_agent_customer" in sql:
                    name = str(trigger["name"]).replace('"', '""')
                    cur.execute(f'DROP TRIGGER "{name}"')
            cur.execute(
                "UPDATE instances SET controller_id=NULL WHERE id=?",
                ("instance-diagnostics",),
            )
            cur.close()

    def test_legacy_instance_uses_customer_controller_for_failure_alert(self):
        self._simulate_legacy_instance_without_controller()

        self.jobs.apply_result("agent-diagnostics", self._failure())

        alert_id = f"instance-provisioning-failed:{self.created['provisioning_id']}"
        alert = AlertRepository(self.backend).get_alert(alert_id)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["controller_id"], self.controller_id)
        self.assertEqual(alert["level"], "CRITICAL")
        self.assertEqual(alert["instance_id"], "instance-diagnostics")
        self.assertIn("AURORA", alert["message"])


if __name__ == "__main__":
    unittest.main()
