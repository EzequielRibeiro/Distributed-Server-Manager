#!/usr/bin/env python3
"""Issue #977: authenticated DayZ transactions coordinate on the same lock."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "linux" / "runtime"))

import server_update_agent
import maintenance_game_update
from game_data_update_lock import game_data_update_lock, GameDataUpdateLockError


class DayZTransactionLockIntegrationTest(unittest.TestCase):
    def make_context(self, root):
        target = root / "serverfiles"
        target.mkdir()
        config_file = root / "agent-config.json"
        config_file.write_text(json.dumps({"agent_id": "agent-one"}))
        record = {"instance_id": "dayz-one", "agent_id": "agent-one",
                  "game_id": "dayz", "working_directory": str(target)}
        return target, config_file, record

    def test_normal_update_is_blocked_before_installation(self):
        with tempfile.TemporaryDirectory() as td:
            target, cfg, record = self.make_context(Path(td))
            selection = {"game": "dayz", "_server_update": {"instance_id": "dayz-one"}}
            with patch.object(server_update_agent.instance_runtime, "get_instance", return_value=record), patch.object(
                    server_update_agent.instance_runtime, "list_instances", return_value=[record]), patch.dict(
                    "os.environ", {"CAPIVARA_AGENT_CONFIG": str(cfg)}), patch.object(
                    server_update_agent, "detect_update") as detect:
                with game_data_update_lock(target):
                    with self.assertRaises(GameDataUpdateLockError):
                        server_update_agent.perform_update(
                            selection, target, lambda _: self.fail("installer ran while locked")
                        )
                detect.assert_not_called()

    def test_maintenance_prepare_is_blocked_before_installation(self):
        with tempfile.TemporaryDirectory() as td:
            target, cfg, record = self.make_context(Path(td))
            selection = {"game": "dayz", "_maintenance_game_update": {"instance_id": "dayz-one"}}
            with patch.object(maintenance_game_update.instance_runtime, "get_instance", return_value=record), patch.object(
                    maintenance_game_update.instance_runtime, "list_instances", return_value=[record]), patch.dict(
                    "os.environ", {"CAPIVARA_AGENT_CONFIG": str(cfg)}), patch.object(
                    maintenance_game_update, "detect_update") as detect:
                with game_data_update_lock(target):
                    with self.assertRaises(GameDataUpdateLockError):
                        maintenance_game_update.prepare(
                            selection, target, lambda _: self.fail("installer ran while locked")
                        )
                detect.assert_not_called()

    def test_foreign_agent_cannot_create_update_lock_file(self):
        with tempfile.TemporaryDirectory() as td:
            target, cfg, record = self.make_context(Path(td))
            record["agent_id"] = "other-agent"
            selection = {"game": "dayz", "_server_update": {"instance_id": "dayz-one"}}
            with patch.object(server_update_agent.instance_runtime, "get_instance", return_value=record), patch.dict(
                    "os.environ", {"CAPIVARA_AGENT_CONFIG": str(cfg)}):
                with self.assertRaises(server_update_agent.ServerUpdateError):
                    server_update_agent.perform_update(selection, target, lambda _: None)
            self.assertFalse((target.parent / ".serverfiles.capivara-game-data-update.lock").exists())

    def test_finalize_and_rollback_must_use_lock(self):
        # Validate both call sites use the same installation-bound lock and
        # the original operation revalidates state after lock acquisition.
        source = (ROOT / "agents/linux/runtime/maintenance_game_update.py").read_text()
        self.assertIn("with game_data_update_lock(Path(checkpoint[\"target\"]), timeout=3):", source)
        self.assertIn("return _finalize_locked(selection, transaction_id)", source)
        self.assertIn("return _rollback_transaction_locked(selection, transaction_id)", source)


if __name__ == "__main__":
    unittest.main()
