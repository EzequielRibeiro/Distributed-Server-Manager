#!/usr/bin/env python3
"""Isolated, no-I/O regression tests for recovered provisioning evidence."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
from recovered_provisioning_evidence import recovered_previous_failure

BASE = {
    "status": "failed", "instance_id": "minecraft-005", "agent_id": "agent-horizon",
    "completed_at": "2026-10-22T22:18:50Z",
}
PROOF = {
    "status": "recovered", "operation": "minecraft_serverpack_migration",
    "filesystem_status": "recovered", "original_loader_verified": True,
    "authenticated_agent_observation": True,
    "instance_id": "minecraft-005", "agent_id": "agent-horizon",
    "recovered_at": "2026-10-23T23:28:00Z",
    "observed_at": "2026-10-23T23:29:00Z",
}


def evaluate(provisioning=None, proof=None, **overrides):
    args = dict(expected_instance_id="minecraft-005", expected_agent_id="agent-horizon",
                live_state="running", reconcile_status="healthy")
    args.update(overrides)
    return recovered_previous_failure(
        BASE if provisioning is None else provisioning,
        PROOF if proof is None else proof, **args)


class RecoveredProvisioningEvidenceTest(unittest.TestCase):
    def test_verified_recovery(self):
        self.assertTrue(evaluate())

    def test_cannot_rewrite_newer_failed_attempt(self):
        self.assertFalse(evaluate(provisioning={**BASE, "completed_at": "2026-10-24T00:00:00Z"}))

    def test_cross_agent_or_instance_rejected(self):
        for field in ("agent_id", "instance_id"):
            self.assertFalse(evaluate(proof={**PROOF, field: "other"}))

    def test_missing_authenticated_observation(self):
        self.assertFalse(evaluate(proof={**PROOF, "authenticated_agent_observation": False}))

    def test_not_recovered_or_loader_unverified(self):
        self.assertFalse(evaluate(proof={**PROOF, "status": "failed"}))
        self.assertFalse(evaluate(proof={**PROOF, "original_loader_verified": False}))

    def test_process_not_healthy(self):
        self.assertFalse(evaluate(live_state="stopped"))
        self.assertFalse(evaluate(reconcile_status="degraded"))

    def test_invalid_timestamps_fail_closed(self):
        self.assertFalse(evaluate(proof={**PROOF, "recovered_at": "broken"}))
        self.assertFalse(evaluate(proof={**PROOF, "observed_at": "2026-10-23T23:27:00Z"}))

    def test_new_provisioning_not_suppressed(self):
        for status in ("running", "completed", "queued"):
            self.assertFalse(evaluate(provisioning={**BASE, "status": status}))


if __name__ == "__main__":
    unittest.main()
