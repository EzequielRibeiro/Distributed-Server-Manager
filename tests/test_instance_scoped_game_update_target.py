"""Regression tests for instance-scoped update target selection."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.linux.runtime import game_data_executor as executor


class InstanceScopedUpdateTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.target = root / "pool" / "dayz" / "serverfiles"
        self.target.mkdir(parents=True)
        self.executable = self.target / "DayZServer"
        self.executable.write_bytes(b"binary")
        self.record = {
            "instance_id": "dayz-homolog-node1-isolated",
            "game_id": "dayz",
            "working_directory": str(self.target),
            "executable": str(self.executable),
        }
        fake = types.SimpleNamespace(get_instance=lambda iid: self.record if iid == self.record["instance_id"] else None)
        self.module_patch = patch.dict(sys.modules, {"instance_runtime": fake})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def selection(self, operation="check"):
        return {"game": "dayz", "_server_update": {
            "instance_id": "dayz-homolog-node1-isolated", "operation": operation}}

    def test_check_and_update_use_registered_storage_pool(self):
        for operation in ("check", "update", "maintenance"):
            with self.subTest(operation=operation):
                self.assertEqual(executor._target_for(self.selection(operation)), self.target)

    def test_maintenance_metadata_without_server_update(self):
        selection = {"game": "dayz", "_maintenance_game_update": {
            "instance_id": "dayz-homolog-node1-isolated"}}
        self.assertEqual(executor._target_for(selection), self.target)

    def test_missing_instance_fails_closed(self):
        selection = self.selection()
        selection["_server_update"]["instance_id"] = "missing"
        with self.assertRaises(RuntimeError):
            executor._target_for(selection)

    def test_game_mismatch_fails_closed(self):
        selection = self.selection()
        selection["game"] = "minecraft"
        with self.assertRaises(RuntimeError):
            executor._target_for(selection)

    def test_executable_escape_fails_closed(self):
        self.record["executable"] = str(Path(self.temp.name) / "other")
        with self.assertRaises(RuntimeError):
            executor._target_for(self.selection())

    def test_unscoped_keeps_shared_target(self):
        self.assertEqual(executor._target_for({"game": "dayz", "install_dir": "serverfiles"}),
                         executor.GAME_DATA_ROOT / "dayz" / "serverfiles")


if __name__ == "__main__":
    unittest.main()
