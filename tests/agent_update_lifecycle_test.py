#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
UPDATER_DIR = ROOT / "agents" / "linux" / "updater"
for path in (RUNTIME, UPDATER_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import local_cli
import update_state
import updater


class AgentUpdateLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.install = self.root / "install"
        self.cli = self.root / "bin" / "cap"
        self.config = {"capivara_version": "1.4.0"}

        self.original_state = (
            update_state.STATE_DIR,
            update_state.REQUEST_PATH,
            update_state.RESULT_PATH,
            update_state.HISTORY_DIR,
        )
        update_state.STATE_DIR = self.state
        update_state.REQUEST_PATH = self.state / "update-request.json"
        update_state.RESULT_PATH = self.state / "update-result.json"
        update_state.HISTORY_DIR = self.state / "update-history"

        self.original_updater = (
            updater.STATE_DIR,
            updater.INSTALL_ROOT,
            updater.CLI_PATH,
            updater.REQUEST_PATH,
            updater.RESULT_PATH,
            updater.HISTORY_DIR,
        )
        updater.STATE_DIR = self.state
        updater.INSTALL_ROOT = self.install
        updater.CLI_PATH = self.cli
        updater.REQUEST_PATH = self.state / "update-request.json"
        updater.RESULT_PATH = self.state / "update-result.json"
        updater.HISTORY_DIR = self.state / "update-history"

    def tearDown(self):
        (
            update_state.STATE_DIR,
            update_state.REQUEST_PATH,
            update_state.RESULT_PATH,
            update_state.HISTORY_DIR,
        ) = self.original_state
        (
            updater.STATE_DIR,
            updater.INSTALL_ROOT,
            updater.CLI_PATH,
            updater.REQUEST_PATH,
            updater.RESULT_PATH,
            updater.HISTORY_DIR,
        ) = self.original_updater
        self.temp.cleanup()

    def test_update_status_and_history_are_read_only_views(self):
        self.state.mkdir(parents=True)
        update_state.REQUEST_PATH.write_text(
            json.dumps({"desired_version": "1.5.0", "channel": "stable"}),
            encoding="utf-8",
        )
        updater._write_result("failed", desired_version="1.5.0", error="test")
        snapshot = update_state.status()
        self.assertEqual(snapshot["pending"]["desired_version"], "1.5.0")
        self.assertEqual(snapshot["last_result"]["status"], "failed")
        values = update_state.history(10)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["status"], "failed")

    def test_update_check_reads_github_release_without_staging_request(self):
        with patch.object(local_cli, "_installed_version", return_value="1.4.0"), patch.object(
            local_cli,
            "_github_json",
            return_value={
                "tag_name": "v1.5.0",
                "html_url": "https://github.example/releases/v1.5.0",
                "draft": False,
                "prerelease": False,
            },
        ):
            payload = local_cli._update_check(self.config, "stable")
        self.assertTrue(payload["update_available"])
        self.assertEqual(payload["latest_version"], "1.5.0")
        self.assertFalse(update_state.REQUEST_PATH.exists())

    def test_cli_reconciliation_allows_missing_or_owned_symlink_only(self):
        self.install.joinpath("runtime").mkdir(parents=True)
        local_cli_path = self.install / "runtime" / "local_cli.py"
        local_cli_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        self.assertEqual(updater._validate_cli_target(), (False, None))
        self.cli.parent.mkdir(parents=True)
        os.symlink(str(local_cli_path), self.cli)
        existed, target = updater._validate_cli_target()
        self.assertTrue(existed)
        self.assertEqual(target, str(local_cli_path))
        self.cli.unlink()
        self.cli.write_text("foreign", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            updater._validate_cli_target()

    def test_manifest_requires_matching_channel_and_version(self):
        manifest = {
            "kind": "CapivaraAgentPackage",
            "platform": "linux",
            "version": "1.5.0",
            "channel": "stable",
        }
        updater._verify_manifest(manifest, "1.5.0", "stable")
        with self.assertRaises(RuntimeError):
            updater._verify_manifest(manifest, "1.5.1", "stable")
        with self.assertRaises(RuntimeError):
            updater._verify_manifest(manifest, "1.5.0", "beta")

    def test_transaction_rollback_restores_file_and_removes_new_cli_link(self):
        package = self.root / "package"
        source = package / "agent.py"
        source.parent.mkdir(parents=True)
        source.write_text("new-agent\n", encoding="utf-8")

        destination = self.install / "runtime" / "agent.py"
        destination.parent.mkdir(parents=True)
        destination.write_text("old-agent\n", encoding="utf-8")

        local_cli_path = self.install / "runtime" / "local_cli.py"
        local_cli_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        cli_existed, old_cli_target = updater._validate_cli_target()
        self.assertFalse(cli_existed)

        mapping = [(source, destination, 0o755, "agent/runtime/agent.py")]
        backup_root = self.root / "rollback"
        snapshots = updater._snapshot_files(mapping, backup_root)

        updater._apply_files(mapping)
        updater._reconcile_cli()
        self.assertEqual(destination.read_text(encoding="utf-8"), "new-agent\n")
        self.assertTrue(self.cli.is_symlink())

        updater._restore_files(snapshots)
        updater._restore_cli(cli_existed, old_cli_target)

        self.assertEqual(destination.read_text(encoding="utf-8"), "old-agent\n")
        self.assertFalse(self.cli.exists())
        self.assertFalse(self.cli.is_symlink())


if __name__ == "__main__":
    unittest.main()
