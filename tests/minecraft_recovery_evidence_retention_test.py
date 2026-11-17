#!/usr/bin/env python3
"""Preserve recovered Server Pack evidence when a later operation reuses the journal."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "linux" / "runtime"))
import instance_runtime
import runtime_operations as ops

RECOVERED = {
    "instance_id": "mc005", "agent_id": "agent1",
    "operation": "minecraft_serverpack_migration", "status": "recovered",
    "recovered_at": "2026-10-24T08:00:00Z",
    "recovery": {"kind": "MinecraftServerPackMigrationRecovery",
                 "filesystem_status": "recovered",
                 "manual_recovery_required": False,
                 "original_loader_version": "26.1.2.94"},
}

class RecoveryEvidenceRetentionTests(unittest.TestCase):
    def test_next_operation_retains_recovered_journal(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(instance_runtime, "STATE_DIR", Path(temp)):
            ops._atomic(ops._path("mc005"), RECOVERED)
            ops._preserve_recovered_migration("mc005", ops.read_operation("mc005"))
            ops._atomic(ops._path("mc005"), {"instance_id": "mc005", "operation": "status", "status": "completed"})
            self.assertEqual(ops.read_recovered_migration("mc005"), RECOVERED)
    def test_does_not_archive_failed_migration(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(instance_runtime, "STATE_DIR", Path(temp)):
            ops._preserve_recovered_migration("mc005", {**RECOVERED, "status": "failed"})
            self.assertFalse((Path(temp) / "recovery-evidence" / "mc005.json").exists())
    def test_conflicting_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(instance_runtime, "STATE_DIR", Path(temp)):
            ops._preserve_recovered_migration("mc005", RECOVERED)
            with self.assertRaises(RuntimeError):
                ops._preserve_recovered_migration("mc005", {**RECOVERED, "recovered_at": "2026-10-24T09:00:00Z"})

if __name__ == "__main__":
    unittest.main()
