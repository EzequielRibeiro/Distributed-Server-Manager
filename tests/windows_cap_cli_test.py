#!/usr/bin/env python3
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "windows" / "runtime"
SERVICE = ROOT / "agents" / "windows" / "service"
RELEASE = ROOT / "release"

spec = importlib.util.spec_from_file_location("windows_local_cli", RUNTIME / "local_cli.py")
local_cli = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(local_cli)


class WindowsCapCliTest(unittest.TestCase):
    def test_secret_fields_are_redacted(self):
        value = {
            "agent_id": "agent-test",
            "credential_id": "cred-test",
            "credential_secret": "do-not-print",
            "pairing_token": "do-not-print-either",
            "nested": {"password_file": "secret-path"},
        }
        result = local_cli._sanitized(value)
        self.assertEqual(result["agent_id"], "agent-test")
        self.assertEqual(result["credential_id"], "cred-test")
        self.assertEqual(result["credential_secret"], "<redacted>")
        self.assertEqual(result["pairing_token"], "<redacted>")
        self.assertEqual(result["nested"]["password_file"], "<redacted>")

    def test_cli_contract_contains_expected_commands(self):
        parser = local_cli.build_parser()
        sub_action = next(action for action in parser._actions if action.dest == "command")
        expected = {
            "status",
            "check",
            "doctor",
            "history",
            "start",
            "stop",
            "restart",
            "version",
            "config",
            "relink",
            "uninstall",
        }
        self.assertTrue(expected.issubset(set(sub_action.choices)))

    def test_launchers_are_shipped_and_machine_path_is_registered(self):
        self.assertTrue((RUNTIME / "cap.cmd").is_file())
        self.assertTrue((RUNTIME / "cap.ps1").is_file())
        launcher = (SERVICE / "run-agent.ps1").read_text(encoding="utf-8")
        self.assertIn("SetEnvironmentVariable('Path', $newMachinePath, 'Machine')", launcher)
        self.assertIn("$runtimeDir = Split-Path -Parent $AgentScript", launcher)

    def test_windows_package_builder_includes_cli_launchers(self):
        source = (RELEASE / "build_windows_agent_package.py").read_text(encoding="utf-8")
        self.assertIn('endswith((".py",".ps1",".cmd"))', source)
        self.assertIn('"local_cap_cli":True', source)

    def test_uninstall_is_confirmation_gated_and_preserves_data_by_default(self):
        source = (RUNTIME / "local_cli.py").read_text(encoding="utf-8")
        self.assertIn("args.confirm != agent_id", source)
        self.assertIn('p.add_argument("--purge-data", action="store_true")', source)
        self.assertIn("Data preserved at", source)


if __name__ == "__main__":
    unittest.main()
