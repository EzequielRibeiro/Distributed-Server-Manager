#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_connection_api import test_agent_connection_for_user
from agent_ssh_deploy import SSHResult


class AgentConnectionControllerProbeTest(unittest.TestCase):
    def setUp(self):
        self.user = {"role": "admin", "username": "admin"}

    def test_remote_connection_requires_controller_url(self):
        with self.assertRaisesRegex(ValueError, "controller_url is required"):
            test_agent_connection_for_user(
                self.user,
                {
                    "platform": "windows",
                    "ssh_host": "win-node",
                    "ssh_user": "Administrator",
                },
                ssh_runner=lambda argv, stdin_text, timeout: SSHResult(1, "", "unexpected"),
            )

    def test_windows_preflight_checks_controller_from_remote_host(self):
        calls = []

        def runner(argv, stdin_text, timeout):
            calls.append(list(argv))
            if len(calls) == 1:
                return SSHResult(0, "CAPIVARA_WINDOWS_PREFLIGHT_OK\nAMD64\n", "")
            return SSHResult(0, "CAPIVARA_CONTROLLER_REACHABLE_OK\n", "")

        result = test_agent_connection_for_user(
            self.user,
            {
                "platform": "windows",
                "ssh_host": "win-node",
                "ssh_user": "Administrator",
                "controller_url": "https://controller.example:9443",
            },
            ssh_runner=runner,
        )
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["controller_reachable"])
        self.assertEqual(result["controller_url"], "https://controller.example:9443")

    def test_remote_controller_probe_failure_is_reported(self):
        calls = []

        def runner(argv, stdin_text, timeout):
            calls.append(list(argv))
            if len(calls) == 1:
                return SSHResult(0, "CAPIVARA_WINDOWS_PREFLIGHT_OK\nAMD64\n", "")
            return SSHResult(1, "", "TLS trust relationship failed")

        with self.assertRaisesRegex(ValueError, "Controller URL is not reachable"):
            test_agent_connection_for_user(
                self.user,
                {
                    "platform": "windows",
                    "ssh_host": "win-node",
                    "ssh_user": "Administrator",
                    "controller_url": "https://192.0.2.10:9443",
                },
                ssh_runner=runner,
            )


if __name__ == "__main__":
    unittest.main()
