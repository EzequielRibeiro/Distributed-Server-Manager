#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, ROOT / "database", ROOT / "dashboard", RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import instance_runtime
import privileged_materialization


class AgentInstanceRemoveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        self.original_paths = (
            instance_runtime.STATE_DIR,
            instance_runtime.INSTANCE_DIR,
            instance_runtime.RESULT_DIR,
            instance_runtime.HISTORY_DIR,
        )
        self.original_remove = privileged_materialization.remove
        instance_runtime.STATE_DIR = self.state
        instance_runtime.INSTANCE_DIR = self.state / "instances"
        instance_runtime.RESULT_DIR = self.state / "instance-results"
        instance_runtime.HISTORY_DIR = self.state / "instance-command-history"
        self.config = {"agent_id": "agent-one"}

    def tearDown(self):
        (
            instance_runtime.STATE_DIR,
            instance_runtime.INSTANCE_DIR,
            instance_runtime.RESULT_DIR,
            instance_runtime.HISTORY_DIR,
        ) = self.original_paths
        privileged_materialization.remove = self.original_remove
        self.temp.cleanup()

    def test_remove_is_agent_owned_and_idempotent_by_command_id(self):
        instance_runtime.register_instance({
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "runtime_id": "runtime-one",
            "adapter": "systemd",
        })
        calls = []

        def fake_remove(config, instance_id):
            calls.append((config["agent_id"], instance_id))
            instance_runtime._instance_path(instance_id).unlink(missing_ok=True)
            return {"instance_id": instance_id, "operation": {"changed": True}}

        privileged_materialization.remove = fake_remove
        command = {
            "command_id": "cmd-remove",
            "instance_id": "instance-one",
            "action": "remove",
        }
        first = instance_runtime.handle_command(self.config, command)
        second = instance_runtime.handle_command(self.config, command)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["action"], "remove")
        self.assertTrue(first["result"]["shared_game_data_preserved"])
        self.assertEqual(calls, [("agent-one", "instance-one")])
        self.assertIsNone(instance_runtime.get_instance("instance-one"))

    def test_remove_rejects_foreign_instance(self):
        instance_runtime.register_instance({
            "instance_id": "foreign",
            "agent_id": "agent-two",
            "runtime_id": "runtime-two",
            "adapter": "systemd",
        })
        result = instance_runtime.handle_command(self.config, {
            "command_id": "cmd-remove-foreign",
            "instance_id": "foreign",
            "action": "remove",
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("another Agent", result["error"])


if __name__ == "__main__":
    unittest.main()
