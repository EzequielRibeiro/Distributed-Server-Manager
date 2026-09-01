#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "windows" / "runtime"

for item in (ROOT, RUNTIME):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import uninstall_client


class WindowsUninstallTerminalSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        self.install_root = self.root / "Program Files" / "CapivaraAgent"
        self.data_root = self.root / "ProgramData" / "CapivaraAgent"
        self.state_root = self.data_root / "state"
        self.temp_root = self.root / "Temp"
        self.config_path = self.data_root / "agent.json"

        service = self.install_root / "service"
        service.mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

        source_script = (
            ROOT
            / "agents"
            / "windows"
            / "service"
            / "uninstall-agent.ps1"
        )

        (
            service / "uninstall-agent.ps1"
        ).write_bytes(source_script.read_bytes())

        self.secret = "secret-value-that-must-not-enter-command-line"

        self.config_path.write_text(
            json.dumps(
                {
                    "controller_url":
                        "https://controller.example.test:9443",
                    "agent_id": "agent-terminal-security",
                    "fingerprint": "sha256:terminal-security",
                    "credential_id": "credential-terminal",
                    "credential_secret": self.secret,
                }
            ),
            encoding="utf-8",
        )

        self.patches = [
            mock.patch.object(
                uninstall_client,
                "INSTALL_ROOT",
                self.install_root,
            ),
            mock.patch.object(
                uninstall_client,
                "STATE_DIR",
                self.state_root,
            ),
            mock.patch.object(
                uninstall_client,
                "TEMP_DIR",
                self.temp_root,
            ),
            mock.patch.object(
                uninstall_client,
                "CONFIG_PATH",
                self.config_path,
            ),
        ]

        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()

        self.temp.cleanup()

    def test_terminal_identity_is_staged_outside_agent_data(self):
        path = uninstall_client._stage_terminal_identity(
            "uninstall-security-1"
        )

        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.temp_root)

        data = json.loads(
            path.read_text(encoding="utf-8")
        )

        self.assertEqual(
            data["agent_id"],
            "agent-terminal-security",
        )
        self.assertEqual(
            data["credential_id"],
            "credential-terminal",
        )
        self.assertEqual(
            data["credential_secret"],
            self.secret,
        )
        self.assertEqual(
            data["request_id"],
            "uninstall-security-1",
        )

    def test_secret_never_enters_scheduled_task_arguments(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append([str(item) for item in command])

            return mock.Mock(
                returncode=0,
                stdout="",
                stderr="",
            )

        with mock.patch.object(
            uninstall_client.subprocess,
            "run",
            side_effect=fake_run,
        ):
            launched = uninstall_client._launch_uninstall(
                "uninstall-security-2",
                "preserve-data",
            )

        self.assertTrue(launched)

        serialized = "\n".join(
            " ".join(call)
            for call in calls
        )

        self.assertNotIn(
            self.secret,
            serialized,
        )

        self.assertNotIn(
            "credential-terminal",
            serialized,
        )

        self.assertIn(
            "-TerminalIdentityPath",
            serialized,
        )

        identity_path = (
            uninstall_client._terminal_identity_path(
                "uninstall-security-2"
            )
        )

        self.assertIn(
            str(identity_path),
            serialized,
        )

        self.assertTrue(identity_path.exists())

    def test_launcher_failure_removes_sensitive_snapshot_and_lock(self):
        call_number = 0

        def fake_run(command, **kwargs):
            nonlocal call_number
            call_number += 1

            if call_number == 2:
                raise uninstall_client.subprocess.CalledProcessError(
                    1,
                    command,
                    stderr="simulated launch failure",
                )

            return mock.Mock(
                returncode=0,
                stdout="",
                stderr="",
            )

        request_id = "uninstall-security-3"

        with mock.patch.object(
            uninstall_client.subprocess,
            "run",
            side_effect=fake_run,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "failed to launch Windows uninstall task",
            ):
                uninstall_client._launch_uninstall(
                    request_id,
                    "preserve-data",
                )

        identity_path = (
            uninstall_client._terminal_identity_path(
                request_id
            )
        )

        _staging, launch_lock = (
            uninstall_client._launch_paths(
                request_id
            )
        )

        self.assertFalse(identity_path.exists())
        self.assertFalse(launch_lock.exists())

    def test_powershell_terminal_contract_is_secret_safe(self):
        script = (
            ROOT
            / "agents"
            / "windows"
            / "service"
            / "uninstall-agent.ps1"
        ).read_text(encoding="utf-8")

        required = (
            "TerminalIdentityPath",
            "LaunchLockPath",
            "PSCommandPath",
            "Send-TerminalUninstallResult",
            "/api/agent/uninstall/result",
            "Invoke-RestMethod",
            'X-Capivara-Agent-Credential',
            'X-Capivara-Agent-Secret',
            'X-Capivara-Agent-Fingerprint',
            '-Status "completed"',
            '-Status "failed"',
            "Remove-Item",
        )

        for value in required:
            self.assertIn(value, script)

        self.assertNotIn(
            'Write-UninstallLog $credentialSecret',
            script,
        )

        self.assertNotIn(
            'Write-Host $credentialSecret',
            script,
        )


if __name__ == "__main__":
    unittest.main()
