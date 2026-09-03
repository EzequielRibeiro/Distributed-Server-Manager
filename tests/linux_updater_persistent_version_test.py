#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
UPDATER_PATH = ROOT / "agents" / "linux" / "updater" / "updater.py"


def _load_updater():
    spec = importlib.util.spec_from_file_location("capivara_linux_updater_version_test", UPDATER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


updater = _load_updater()


class LinuxUpdaterPersistentVersionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "agent.json"
        self.identity = {
            "agent_id": "agent-test",
            "node_id": "node-test",
            "controller_id": "controller-test",
            "controller_url": "https://controller.example:9443",
            "fingerprint": "sha256:test",
            "credential_id": "cred-test",
            "credential_secret": "secret-test",
            "capivara_version": "2.0.20",
        }
        self.config.write_text(json.dumps(self.identity) + "\n", encoding="utf-8")
        os.chmod(self.config, 0o600)
        self.patcher = mock.patch.object(updater, "CONFIG_PATH", self.config)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_sync_updates_only_capivara_version(self):
        updater._sync_persistent_version("2.0.21", dict(self.identity))
        current = json.loads(self.config.read_text(encoding="utf-8"))

        self.assertEqual("2.0.21", current["capivara_version"])
        for key, value in self.identity.items():
            if key != "capivara_version":
                self.assertEqual(value, current[key])
        self.assertEqual(0o600, self.config.stat().st_mode & 0o777)

    def test_sync_refuses_identity_change(self):
        changed = dict(self.identity)
        changed["credential_id"] = "cred-other"
        self.config.write_text(json.dumps(changed) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "identity changed during update"):
            updater._sync_persistent_version("2.0.21", dict(self.identity))

    def test_snapshot_restores_original_version_and_identity(self):
        snapshot = updater._snapshot_persistent_config()
        updater._sync_persistent_version("2.0.21", dict(self.identity))
        updater._restore_persistent_config(snapshot)

        current = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(self.identity, current)
        self.assertEqual(0o600, self.config.stat().st_mode & 0o777)

    def test_validate_persistent_version_detects_mismatch(self):
        with self.assertRaisesRegex(RuntimeError, "persistent capivara_version"):
            updater._validate_persistent_version("2.0.21")

        updater._sync_persistent_version("2.0.21", dict(self.identity))
        updater._validate_persistent_version("2.0.21")


if __name__ == "__main__":
    unittest.main()
