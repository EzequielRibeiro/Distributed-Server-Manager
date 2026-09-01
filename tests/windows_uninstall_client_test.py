#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
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
                "CAPIVARA_AGENT_TEMP_DIR": str(Path(self.temp.name) / "Temp"),
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

    def command(self, *, mode="preserve-data", phase="prepare"):
        return {
            "kind": "AgentUninstallCommand",
            "schema_version": 1,
            "request_id": "uninstall-test-1",
            "action": "uninstall-agent",
            "mode": mode,
            "phase": phase,
        }

    def test_prepare_validates_typed_contract_and_persists_result(self):
        result = self.client.handle_command(self.command())
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(self.client.read_result()["request_id"], "uninstall-test-1")
        staged = json.loads(self.client.REQUEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(staged["mode"], "preserve-data")

    def test_rejects_arbitrary_action_or_phase(self):
        command = self.command()
        command["action"] = "powershell"
        with self.assertRaisesRegex(ValueError, "invalid uninstall action"):
            self.client.handle_command(command)
        command = self.command(phase="execute-shell")
        with self.assertRaisesRegex(ValueError, "invalid uninstall phase"):
            self.client.handle_command(command)

    def test_commit_requires_matching_staged_request(self):
        self.client.handle_command(self.command())
        command = self.command(phase="commit")
        command["request_id"] = "uninstall-other"
        with self.assertRaisesRegex(RuntimeError, "does not match commit"):
            self.client.handle_command(command)

    @patch("subprocess.run")
    def test_commit_launches_independent_preserve_data_uninstall(self, run):
        self.client.handle_command(self.command())

        result = self.client.handle_command(
            self.command(phase="commit")
        )

        self.assertEqual(result["status"], "committed")
        self.assertEqual(run.call_count, 2)

        register_args = run.call_args_list[0].args[0]
        start_args = run.call_args_list[1].args[0]

        self.assertIn("-File", register_args)
        self.assertIn("-TaskName", register_args)
        self.assertIn("-Execute", register_args)
        self.assertIn("-Arguments", register_args)

        task_name_index = register_args.index("-TaskName") + 1
        task_name = register_args[task_name_index]

        self.assertEqual(
            task_name,
            "CapivaraAgent-Uninstall-uninstall-test-1",
        )

        argument_index = register_args.index("-Arguments") + 1
        uninstall_args = register_args[argument_index]

        self.assertIn("-File", uninstall_args)
        self.assertIn(
            "capivara-uninstall-uninstall-test-1.ps1",
            uninstall_args,
        )
        self.assertIn("-LauncherTaskName", uninstall_args)
        self.assertIn(
            "CapivaraAgent-Uninstall-uninstall-test-1",
            uninstall_args,
        )
        self.assertNotIn("-Command", uninstall_args)
        self.assertNotIn("-Purge", uninstall_args)

        self.assertEqual(start_args[0], "schtasks.exe")
        self.assertIn("/Run", start_args)
        self.assertNotIn("/Create", start_args)
        self.assertNotIn("/SC", start_args)
        self.assertNotIn("/ST", start_args)

        self.assertEqual(
            self.client.read_result()["status"],
            "committed",
        )

    @patch("subprocess.run")
    def test_commit_replay_does_not_spawn_again(self, run):
        self.client.handle_command(self.command())
        first = self.client.handle_command(self.command(phase="commit"))
        second = self.client.handle_command(self.command(phase="commit"))
        self.assertEqual(first["status"], "committed")
        self.assertEqual(second["status"], "committed")
        self.assertEqual(run.call_count, 2)

    @patch("subprocess.run")
    def test_committed_request_recovers_when_launch_lock_is_missing(self, run):
        self.client.handle_command(self.command())
        self.client.handle_command(self.command(phase="commit"))

        _staging, launch_lock = self.client._launch_paths(
            "uninstall-test-1"
        )
        launch_lock.unlink()

        recovered = self.client.resume_pending_commit()

        self.assertTrue(recovered)
        self.assertEqual(run.call_count, 4)
        self.assertTrue(launch_lock.exists())

    @patch("subprocess.run")
    def test_commit_adds_purge_only_for_explicit_purge_mode(self, run):
        self.client.handle_command(
            self.command(mode="purge")
        )

        result = self.client.handle_command(
            self.command(
                mode="purge",
                phase="commit",
            )
        )

        self.assertEqual(result["mode"], "purge")
        self.assertEqual(run.call_count, 2)

        register_args = run.call_args_list[0].args[0]

        self.assertIn("-Arguments", register_args)

        argument_index = register_args.index("-Arguments") + 1
        uninstall_args = register_args[argument_index]

        self.assertIn("-Purge", uninstall_args)
        self.assertNotIn("/SC", register_args)
        self.assertNotIn("/ST", register_args)

if __name__ == "__main__":
    unittest.main()
