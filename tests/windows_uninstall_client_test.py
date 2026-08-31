#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "agents" / "windows" / "runtime" / "uninstall_client.py"


class WindowsUninstallClientTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.program_data = Path(self.temp.name) / "ProgramData"
        self.program_files = Path(self.temp.name) / "ProgramFiles"
        self.install_root = self.program_files / "CapivaraAgent"
        self.state_dir = self.program_data / "CapivaraAgent" / "state"
        service = self.install_root / "service"
        service.mkdir(parents=True)
        (service / "uninstall-agent.ps1").write_text("param([switch]$Purge)\n", encoding="utf-8")
        self.env = patch.dict(
            os.environ,
            {
                "PROGRAMDATA": str(self.program_data),
                "ProgramFiles": str(self.program_files),
                "CAPIVARA_AGENT_ROOT": str(self.install_root),
                "CAPIVARA_AGENT_STATE_DIR": str(self.state_dir),
            },
            clear=False,
        )
        self.env.start()
        spec = importlib.util.spec_from_file_location("cap_uninstall_client_test", MODULE)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.client = module

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def command(self, *, mode="preserve-data"):
        return {
            "kind": "AgentUninstallCommand",
            "schema_version": 1,
            "request_id": "uninstall-test-1",
            "action": "uninstall-agent",
            "mode": mode,
        }

    def test_accept_validates_typed_contract_and_persists_result(self):
        result = self.client.accept_command(self.command())
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(self.client.read_result()["request_id"], "uninstall-test-1")
        staged = json.loads(self.client.REQUEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(staged["mode"], "preserve-data")

    def test_rejects_arbitrary_action(self):
        command = self.command()
        command["action"] = "powershell"
        with self.assertRaisesRegex(ValueError, "invalid uninstall action"):
            self.client.accept_command(command)

    def test_commit_requires_matching_staged_request(self):
        self.client.accept_command(self.command())
        with self.assertRaisesRegex(RuntimeError, "does not match commit"):
            self.client.commit("uninstall-other")

    @patch("subprocess.Popen")
    def test_commit_launches_detached_preserve_data_uninstall(self, popen):
        self.client.accept_command(self.command())
        result = self.client.commit("uninstall-test-1")
        self.assertEqual(result["status"], "committed")
        args = popen.call_args.args[0]
        command = args[-1]
        self.assertIn("uninstall-agent.ps1", command)
        self.assertNotIn("-Purge", command)

    @patch("subprocess.Popen")
    def test_commit_adds_purge_only_for_explicit_purge_mode(self, popen):
        self.client.accept_command(self.command(mode="purge"))
        result = self.client.commit("uninstall-test-1")
        self.assertEqual(result["mode"], "purge")
        self.assertIn("-Purge", popen.call_args.args[0][-1])


if __name__ == "__main__":
    unittest.main()
