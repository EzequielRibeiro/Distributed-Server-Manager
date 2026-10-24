#!/usr/bin/env python3
"""Integrated Controller recovery decision -> customer projection, no live mutation."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in ("dashboard", "database"):
    sys.path.insert(0, str(ROOT / folder))
from minecraft_recovery_assessment import recovery_assessment
from minecraft_recovery_customer_projection import visible_provision_after_recovery

FAILED = {"instance_id":"mc005", "agent_id":"hybrid1", "status":"failed",
          "completed_at":"2026-10-23T20:00:00Z", "stage":"failed", "progress":99}
RECOVERY = {"source":"controller.authenticated_agent_recovery",
            "agent_id":"hybrid1", "instance_id":"mc005",
            "occurred_at":"2026-10-23T21:00:00Z",
            "data":{"observed_at":"2026-10-23T21:01:00Z",
                    "original_loader_version":"26.1.2.94"}}
PROOF = {"source":"controller.authenticated_agent_recovery",
         "agent_id":"hybrid1", "instance_id":"mc005",
         "occurred_at":"2026-10-23T21:02:00Z",
         "data":{"recovered_at":"2026-10-23T21:00:00Z",
                 "original_loader_version":"26.1.2.94"}}
HEALTH = {"instance_id":"mc005", "observed_state":"running",
          "reconcile_status":"healthy", "health":"healthy",
          "reported_at":"2026-10-23T21:03:00Z"}

class IntegratedRecoveryProjectionTest(unittest.TestCase):
    def assess(self, *, recovery=RECOVERY, proof=PROOF, health=HEALTH, failed=FAILED):
        with patch("minecraft_recovery_assessment.UniversalEventRepository") as events, \
             patch("minecraft_recovery_assessment.AgentInstanceRuntimeHealthRepository") as health_repo, \
             patch("minecraft_recovery_assessment.AgentInstanceProvisioningRepository") as provision:
            events.return_value.list_events.side_effect = [[recovery], [proof] if proof else []]
            health_repo.return_value.list_for_agent.return_value = [health]
            provision.return_value.latest_for_instance.return_value = failed
            result = recovery_assessment(object(), instance_id="mc005", agent_id="hybrid1")
        return result, visible_provision_after_recovery(FAILED, result)

    def test_fully_verified_recovery_hides_only_customer_warning(self):
        result, visible = self.assess()
        self.assertEqual(result["status"], "recovered_verified")
        self.assertIsNone(visible)
        self.assertEqual(FAILED["progress"], 99)  # persisted history remains intact

    def test_missing_historical_evidence_preserves_customer_warning(self):
        with patch("minecraft_recovery_assessment.UniversalEventRepository") as events:
            events.return_value.list_events.return_value = []
            result = recovery_assessment(object(), instance_id="mc005", agent_id="hybrid1")
        self.assertEqual(result["status"], "missing_recovery_evidence")
        self.assertEqual(visible_provision_after_recovery(FAILED, result), FAILED)
        self.assertEqual(FAILED["progress"], 99)

    def test_later_failure_stays_visible(self):
        result, visible = self.assess(failed={**FAILED,"completed_at":"2026-10-23T22:00:00Z"})
        self.assertFalse(result["allow_clear_previous_failure"])
        self.assertEqual(visible, FAILED)

    def test_unverified_loader_stays_visible(self):
        result, visible = self.assess(proof=None)
        self.assertFalse(result["loader_verified"])
        self.assertEqual(visible, FAILED)

    def test_unhealthy_runtime_stays_visible(self):
        result, visible = self.assess(health={**HEALTH,"reconcile_status":"degraded"})
        self.assertFalse(result["allow_clear_previous_failure"])
        self.assertEqual(visible, FAILED)

    def test_wrong_build_proof_stays_visible(self):
        result, visible = self.assess(proof={**PROOF,"data":{**PROOF["data"],"original_loader_version":"26.1.2.95"}})
        self.assertFalse(result["allow_clear_previous_failure"])
        self.assertEqual(visible, FAILED)

if __name__ == "__main__":
    unittest.main()
