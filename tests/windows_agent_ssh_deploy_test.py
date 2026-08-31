#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_ssh_deploy import AgentDeployError, SSHDeployOptions, SSHResult
from windows_agent_ssh_deploy import (
    bootstrap_windows_agent_ssh,
    remote_windows_agent_present_ssh,
)


class WindowsAgentSSHDeployTest(unittest.TestCase):
    def test_bootstrap_requires_success_marker_and_postinstall_verification(self):
        calls = []

        def runner(argv, stdin_text, timeout):
            calls.append((list(argv), stdin_text, timeout))
            if len(calls) == 1:
                return SSHResult(0, "CAPIVARA_WINDOWS_BOOTSTRAP_OK\n", "")
            return SSHResult(0, "CAPIVARA_WINDOWS_INSTALL_VERIFY_OK\n", "")

        secret = "pairing-DO-NOT-EXPOSE"
        bootstrap_windows_agent_ssh(
            SSHDeployOptions(host="192.168.15.4", ssh_user="ezequiel"),
            controller_url="https://controller.example:9443",
            pairing_token=secret,
            release_tag="v2.0.16",
            runner=runner,
        )

        self.assertEqual(len(calls), 2)
        self.assertNotIn(secret, " ".join(calls[0][0]))
        self.assertIn(secret, calls[0][1])
        self.assertIn("CAPIVARA_WINDOWS_BOOTSTRAP_OK", calls[0][1])
        self.assertIn("CapivaraAgent", calls[0][1])
        self.assertIsNone(calls[1][1])

    def test_zero_exit_without_marker_is_failure(self):
        def runner(argv, stdin_text, timeout):
            return SSHResult(0, "installer returned but no marker\n", "")

        with self.assertRaises(AgentDeployError) as ctx:
            bootstrap_windows_agent_ssh(
                SSHDeployOptions(host="192.168.15.4", ssh_user="ezequiel"),
                controller_url="https://controller.example:9443",
                pairing_token="pairing-secret",
                release_tag="v2.0.16",
                runner=runner,
            )
        self.assertIn("did not confirm installation", str(ctx.exception))
        self.assertNotIn("pairing-secret", str(ctx.exception))

    def test_postinstall_failure_is_failure(self):
        calls = 0

        def runner(argv, stdin_text, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return SSHResult(0, "CAPIVARA_WINDOWS_BOOTSTRAP_OK\n", "")
            return SSHResult(1, "", "postcheck failed")

        with self.assertRaises(AgentDeployError) as ctx:
            bootstrap_windows_agent_ssh(
                SSHDeployOptions(host="192.168.15.4", ssh_user="ezequiel"),
                controller_url="https://controller.example:9443",
                pairing_token="pairing-secret",
                release_tag="v2.0.16",
                runner=runner,
            )
        self.assertIn("postcheck failed", str(ctx.exception))

    def test_existing_agent_detection_uses_current_windows_paths(self):
        observed = {}

        def runner(argv, stdin_text, timeout):
            observed["command"] = list(argv)[-1]
            return SSHResult(0, "", "")

        present = remote_windows_agent_present_ssh(
            SSHDeployOptions(host="192.168.15.4", ssh_user="ezequiel"),
            runner=runner,
        )
        self.assertTrue(present)
        command = observed["command"]
        self.assertIn("EncodedCommand", command)
        self.assertNotIn("ProgramData\\Capivara\\Agent", command)


if __name__ == "__main__":
    unittest.main()
