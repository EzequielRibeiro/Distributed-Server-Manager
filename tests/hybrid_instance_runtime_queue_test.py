#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ROOT / "dashboard" / "workers"
if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))

import hybrid_agent_worker as worker


class _Repository:
    def __init__(self, command):
        self.command = command
        self.delivered = []
        self.applied = []

    def command_for_agent(self, agent_id):
        self.requested_agent = agent_id
        return self.command

    def mark_delivered(self, command_id):
        self.delivered.append(command_id)
        return {"command_id": command_id, "status": "delivered"}

    def apply_result(self, agent_id, result):
        self.applied.append((agent_id, result))
        return {"command_id": result["command_id"], "status": result["status"]}


class HybridInstanceRuntimeQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        state = self.root / "runtime" / "hybrid-agent-state"
        state.mkdir(parents=True)
        (state / "agent.json").write_text(json.dumps({"agent_id": "agent-hybrid"}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_idle_when_controller_has_no_runtime_command(self):
        repo = _Repository(None)
        with patch.object(worker, "AgentInstanceRuntimeRepository", return_value=repo):
            result = worker.process_hybrid_instance_runtime_cycle(object(), self.root, "agent-hybrid")
        self.assertEqual(result, {"status": "idle"})
        self.assertEqual(repo.requested_agent, "agent-hybrid")
        self.assertEqual(repo.delivered, [])

    def test_remove_command_is_delivered_executed_applied_and_cleared(self):
        command = {
            "command_id": "instance-cmd-remove-1",
            "agent_id": "agent-hybrid",
            "instance_id": "instance-01",
            "action": "remove",
        }
        repo = _Repository(command)
        cleared = []

        def handle(config, received):
            self.assertEqual(config["agent_id"], "agent-hybrid")
            self.assertEqual(received, command)
            return {
                "command_id": command["command_id"],
                "instance_id": command["instance_id"],
                "action": "remove",
                "status": "completed",
                "result": {"shared_game_data_preserved": True},
            }

        runtime = SimpleNamespace(handle_command=handle, clear_result=cleared.append)
        with patch.object(worker, "AgentInstanceRuntimeRepository", return_value=repo), patch.object(
            worker, "_instance_runtime_module", return_value=runtime
        ):
            result = worker.process_hybrid_instance_runtime_cycle(object(), self.root, "agent-hybrid")

        self.assertEqual(repo.delivered, [command["command_id"]])
        self.assertEqual(len(repo.applied), 1)
        self.assertEqual(repo.applied[0][0], "agent-hybrid")
        self.assertEqual(repo.applied[0][1]["status"], "completed")
        self.assertEqual(cleared, [command["command_id"]])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["action"], "remove")

    def test_identity_mismatch_is_rejected_before_execution(self):
        state = self.root / "runtime" / "hybrid-agent-state" / "agent.json"
        state.write_text(json.dumps({"agent_id": "another-agent"}), encoding="utf-8")
        command = {
            "command_id": "instance-cmd-1",
            "agent_id": "agent-hybrid",
            "instance_id": "instance-01",
            "action": "status",
        }
        repo = _Repository(command)
        runtime = SimpleNamespace(handle_command=lambda *_: self.fail("must not execute"), clear_result=lambda *_: None)
        with patch.object(worker, "AgentInstanceRuntimeRepository", return_value=repo), patch.object(
            worker, "_instance_runtime_module", return_value=runtime
        ):
            with self.assertRaisesRegex(RuntimeError, "identity does not match"):
                worker.process_hybrid_instance_runtime_cycle(object(), self.root, "agent-hybrid")


if __name__ == "__main__":
    unittest.main()
