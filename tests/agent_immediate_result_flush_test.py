from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import agent


class AgentImmediateResultFlushTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "agent_id": "agent-1",
            "controller_url": "https://controller.example:9443",
            "credential_id": "cred-1",
            "credential_secret": "secret",
            "fingerprint": "sha256:test",
            "heartbeat_interval_seconds": 30,
            "degraded_after_seconds": 60,
            "offline_after_seconds": 120,
        }

    def test_flush_posts_final_instance_result_without_full_inventory(self):
        final = {"command_id": "cmd-1", "instance_id": "srv-1", "action": "restart", "status": "completed"}
        posted = []
        cleared = []

        def fake_post(url, payload, headers=None):
            posted.append((url, payload, headers))
            return {"instance_state": {"command_id": "cmd-1", "status": "completed"}}

        with patch.object(agent, "_host_identity", return_value="sha256:host"), \
             patch.object(agent, "read_instance_result", return_value=final), \
             patch.object(agent, "read_console_result", return_value=None), \
             patch.object(agent, "read_file_result", return_value=None), \
             patch.object(agent, "read_resource_result", return_value=None), \
             patch.object(agent, "read_artifact_result", return_value=None), \
             patch.object(agent, "read_doctor_result", return_value=None), \
             patch.object(agent, "clear_instance_result", side_effect=cleared.append), \
             patch.object(agent, "_post", side_effect=fake_post), \
             patch.object(agent, "_inventory", side_effect=AssertionError("full inventory must not be built")):
            response = agent._flush_command_results(self.config)

        self.assertEqual(response["instance_state"]["status"], "completed")
        self.assertEqual(cleared, ["cmd-1"])
        self.assertEqual(len(posted), 1)
        payload = posted[0][1]
        self.assertEqual(payload["instance_result"], final)
        self.assertEqual(payload["agent_id"], "agent-1")
        self.assertEqual(payload["host_identity"], "sha256:host")
        self.assertNotIn("instances", payload)
        self.assertNotIn("instance_telemetry", payload)

    def test_heartbeat_flushes_result_immediately_after_instance_command(self):
        first = {
            "agent_id": "agent-1", "health_status": "online", "status": "active",
            "instance_command": {"command_id": "cmd-1", "instance_id": "srv-1", "action": "restart"},
        }
        report = {"command_id": "cmd-1", "instance_id": "srv-1", "action": "restart", "status": "completed"}
        flushed = {"instance_state": {"command_id": "cmd-1", "instance_id": "srv-1", "action": "restart", "status": "completed"}}
        with patch.object(agent, "_inventory", return_value={"agent_id": "agent-1"}), \
             patch.object(agent, "_post", return_value=first), \
             patch.object(agent, "handle_instance_command", return_value=report), \
             patch.object(agent, "_flush_command_results", return_value=flushed) as flush:
            response = agent.heartbeat(self.config)
        flush.assert_called_once_with(self.config)
        self.assertEqual(response["instance_state"], flushed["instance_state"])
        self.assertNotIn("instance_command", response)


if __name__ == "__main__":
    unittest.main()
