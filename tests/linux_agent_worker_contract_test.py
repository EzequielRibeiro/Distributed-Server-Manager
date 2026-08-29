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
        spec = importlib.util.spec_from_file_location("capivara_linux_agent_contract", AGENT_PATH)
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
        self.assertTrue(callable(module._heartbeat))
        self.assertTrue(callable(module._host_identity))

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
            "controller_timeout_seconds": 30,
        }

        with mock.patch.object(module, "_inventory", return_value={"agent_id": "agent-test"}), \
             mock.patch.object(module, "_ssl_context", return_value=None), \
             mock.patch.object(module, "_json_request", return_value={"status": "active"}) as request:
            result = module._heartbeat(config)

        self.assertEqual(result, {"status": "active"})
        request.assert_called_once()
        args, kwargs = request.call_args
        self.assertEqual(args[0], "https://controller.example.test:9443/api/agent/heartbeat")
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
