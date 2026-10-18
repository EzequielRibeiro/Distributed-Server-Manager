"""Maintenance transaction checkpoint must remain bound to its registered install."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.linux.runtime import maintenance_game_update as maintenance


class MaintenanceCheckpointBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.install = self.root / "install"
        self.install.mkdir()
        self.other = self.root / "other"
        self.other.mkdir()
        self.instance = "test-dayz"
        self.record = {"instance_id": self.instance, "agent_id": "agent-test",
                       "game_id": "dayz", "working_directory": str(self.install)}
        self.payload = {"kind": "CapivaraMaintenanceGameUpdateTransaction",
                        "state": "prepared", "instance_id": self.instance,
                        "agent_id": "agent-test", "game_id": "dayz",
                        "target": str(self.install), "affected_instances": [self.instance]}
        self.selection = {"game": "dayz", "_maintenance_game_update": {"instance_id": self.instance}}
        self.txid = "game-update-checkpoint-test"
        self.patch_root = patch.object(maintenance, "TRANSACTION_ROOT", self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.checkpoint = maintenance._path(self.txid)
        self.checkpoint.write_text(json.dumps(self.payload), encoding="utf-8")
        self.patch_record = patch.object(maintenance.instance_runtime, "get_instance",
                                         side_effect=lambda iid: self.record if iid == self.instance else None)
        self.patch_record.start()
        self.addCleanup(self.patch_record.stop)

    def test_unchanged_binding_loads(self):
        checkpoint, path = maintenance._load(self.selection, self.txid)
        self.assertEqual(path, self.checkpoint)
        self.assertEqual(checkpoint["target"], str(self.install))

    def test_moved_installation_rejected(self):
        self.record["working_directory"] = str(self.other)
        with self.assertRaises(maintenance.MaintenanceGameUpdateError):
            maintenance._load(self.selection, self.txid)

    def test_missing_installation_rejected(self):
        self.record["working_directory"] = str(self.root / "missing")
        with self.assertRaises(maintenance.MaintenanceGameUpdateError):
            maintenance._load(self.selection, self.txid)

    def test_affected_instance_mismatch_rejected(self):
        self.payload["affected_instances"] = ["another"]
        self.checkpoint.write_text(json.dumps(self.payload), encoding="utf-8")
        with self.assertRaises(maintenance.MaintenanceGameUpdateError):
            maintenance._load(self.selection, self.txid)

    def test_wrong_agent_rejected(self):
        self.record["agent_id"] = "other-agent"
        with self.assertRaises(maintenance.MaintenanceGameUpdateError):
            maintenance._load(self.selection, self.txid)


if __name__ == "__main__":
    unittest.main()
