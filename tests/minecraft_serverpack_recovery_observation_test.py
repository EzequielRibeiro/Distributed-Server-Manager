#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "linux" / "runtime"))
from minecraft_serverpack_recovery_observation import recovery_observation

JOURNAL = {
    "agent_id": "agent-horizon-server",
    "instance_id": "cli-000001-minecraft-005",
    "operation": "minecraft_serverpack_migration",
    "status": "recovered",
    "recovered_at": "2026-10-23T23:28:00Z",
    "recovery": {
        "kind": "MinecraftServerPackMigrationRecovery",
        "filesystem_status": "recovered",
        "manual_recovery_required": False,
        "original_loader_version": "26.1.2.94",
    }
}

def project(record=None, **kwargs):
    args = dict(instance_id="cli-000001-minecraft-005", agent_id="agent-horizon-server",
                observed_at="2026-10-23T23:30:00Z")
    args.update(kwargs)
    return recovery_observation(JOURNAL if record is None else record, **args)

class RecoveryObservationTests(unittest.TestCase):
    def test_valid_journal_yields_bounded_evidence(self):
        result = project()
        self.assertEqual(result["original_loader_version"], "26.1.2.94")
        self.assertNotIn("authenticated_agent_observation", result)
        self.assertNotIn("original_loader_verified", result)
        self.assertNotIn("healthy", result)
    def test_unsafe_or_wrong_owner_fails_closed(self):
        self.assertIsNone(project(agent_id="other"))
        self.assertIsNone(project(record={**JOURNAL,"status":"failed"}))
        self.assertIsNone(project(record={**JOURNAL,"instance_id":"other"}))
    def test_missing_recovery_proof_fails_closed(self):
        for replacement in (None, {}, {"kind":"MinecraftServerPackMigrationRecovery"}):
            self.assertIsNone(project(record={**JOURNAL,"recovery":replacement}))
    def test_future_or_invalid_time_fails_closed(self):
        self.assertIsNone(project(observed_at="2026-10-23T23:00:00Z"))
        self.assertIsNone(project(observed_at="yesterday"))

if __name__ == "__main__":
    unittest.main()
