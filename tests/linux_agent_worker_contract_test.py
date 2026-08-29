#!/usr/bin/env python3
"""Smoke-test the Linux Agent worker import and heartbeat authentication contract."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents/linux/runtime"
AGENT_PATH = RUNTIME / "agent.py"


def load_agent_module():
    sys.path.insert(0, str(RUNTIME))
    try:
        spec = importlib.util.spec_from_file_location(
            "capivara_linux_agent_contract",
            AGENT_PATH,
        )
        if spec is None or spec.loader is None:
            raise AssertionError("could not load Linux Agent worker")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(RUNTIME))
        except ValueError:
            pass


class LinuxAgentWorkerContractTest(unittest.TestCase):
    def test_worker_imports_complete_runtime_contract(self):
        module = load_agent_module()

        self.assertTrue(callable(module.heartbeat))
        self.assertTrue(callable(module._host_identity))

        # Preserve contracts that already exist in main and must not be lost
        # while adding physical-host identity validation.
        self.assertTrue(callable(module.acknowledge_runtime_events))
        self.assertTrue(callable(module.apply_configuration_commands))
        self.assertTrue(callable(module.handle_instance_command))
        self.assertTrue(callable(module.stage_provisioning_command))

    def test_heartbeat_uses_permanent_agent_credential_headers(self):
        module = load_agent_module()

        config = {
            "agent_id": "agent-test",
            "node_id": "node-test",
            "controller_id": "controller-test",
            "controller_url": "https://controller.example.test:9443",
            "credential_id": "cred-test",
            "credential_secret": "secret-test",
            "fingerprint": "sha256:fingerprint-test",
        }

        with (
            mock.patch.object(
                module,
                "_inventory",
                return_value={"agent_id": "agent-test"},
            ),
            mock.patch.object(
                module,
                "_post",
                return_value={},
            ) as request,
        ):
            result = module.heartbeat(config)

        self.assertEqual(result, {})

        request.assert_called_once()
        args, kwargs = request.call_args

        self.assertEqual(
            args[0],
            "https://controller.example.test:9443/api/agent/heartbeat",
        )

        self.assertEqual(
            kwargs["headers"],
            {
                "X-Capivara-Agent-Credential": "cred-test",
                "X-Capivara-Agent-Secret": "secret-test",
                "X-Capivara-Agent-Fingerprint": "sha256:fingerprint-test",
            },
        )

        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertNotIn("X-Capivara-Agent-ID", kwargs["headers"])
        self.assertNotIn("X-Capivara-Node-ID", kwargs["headers"])


if __name__ == "__main__":
    unittest.main()
