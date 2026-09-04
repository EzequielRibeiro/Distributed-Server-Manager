#!/usr/bin/env python3
from pathlib import Path
import tempfile
import unittest

from dashboard.hybrid_instance_provisioning_client import _paths, _runtime_config


class HybridProvisioningClientTest(unittest.TestCase):
    def test_safe_paths_and_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request, result, log = _paths(root, "instance-provision-abc")
            self.assertTrue(str(request).endswith(".request.json"))
            self.assertTrue(str(result).endswith(".result.json"))
            self.assertTrue(str(log).endswith(".log"))
            config_path, config = _runtime_config(root, "agent-hybrid")
            self.assertEqual(config["agent_id"], "agent-hybrid")
            self.assertTrue(config_path.is_file())

    def test_rejects_unsafe_id(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                _paths(Path(temp), "../escape")



class HybridProvisioningDeliveryTest(unittest.TestCase):
    def test_queued_job_is_staged_and_marked_delivered(self):
        from unittest.mock import patch

        class FakeRepository:
            delivered = []

            def __init__(self, backend):
                self.backend = backend

            def initialize(self):
                return None

            def apply_result(self, agent_id, result):
                return None

            def command_for_agent(self, agent_id):
                self.asserted_agent_id = agent_id
                return {
                    "provisioning_id": "instance-provision-test",
                    "instance_id": "instance-test",
                    "agent_id": agent_id,
                }

            def mark_delivered(self, provisioning_id):
                self.delivered.append(provisioning_id)
                return {
                    "provisioning_id": provisioning_id,
                    "instance_id": "instance-test",
                    "agent_id": "agent-hybrid",
                    "status": "delivered",
                    "current_step": "queued",
                    "progress": 0,
                }

        import dashboard.hybrid_instance_provisioning_client as module

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            with (
                patch.object(module, "AgentInstanceProvisioningRepository", FakeRepository),
                patch.object(module, "_latest_result", return_value=None),
                patch.object(module, "_stage", return_value=True) as stage,
                patch.object(module, "project_agent_provisioning"),
            ):
                result = module.process_hybrid_instance_provisioning_cycle(
                    backend=object(),
                    root=root,
                    agent_id="agent-hybrid",
                )

        self.assertTrue(result["staged"])
        self.assertEqual(
            ["instance-provision-test"],
            FakeRepository.delivered,
        )
        self.assertEqual(
            "instance-provision-test",
            result["state"]["provisioning_id"],
        )
        stage.assert_called_once()

if __name__ == "__main__":
    unittest.main()
