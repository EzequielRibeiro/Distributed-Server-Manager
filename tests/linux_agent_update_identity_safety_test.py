#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
UPDATER_PATH = ROOT / "agents/linux/updater/updater.py"
INSTALLER_PATH = ROOT / "agents/linux/installer/install-agent.sh"


def _load_updater():
    spec = importlib.util.spec_from_file_location("capivara_linux_updater_test", UPDATER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LinuxAgentUpdateIdentitySafetyTest(unittest.TestCase):
    def setUp(self):
        self.updater = _load_updater()

    def _config(self, root: Path, **changes):
        payload = {
            "controller_url": "https://controller.example:9443",
            "agent_id": "agent-0123456789abcdef0123",
            "node_id": "node-0123456789abcdef0123",
            "fingerprint": "sha256:" + "a" * 64,
            "credential_id": "cred-0123456789abcdef0123456789abcdef",
            "credential_secret": "test-secret-not-real",
        }
        payload.update(changes)
        path = root / "agent.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_updater_accepts_complete_persistent_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self._config(Path(temporary))
            with mock.patch.object(self.updater, "CONFIG_PATH", path):
                result = self.updater._load_persistent_identity()
        self.assertEqual(result["agent_id"], "agent-0123456789abcdef0123")

    def test_updater_rejects_missing_permanent_credential(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self._config(Path(temporary), credential_id="", credential_secret="")
            with mock.patch.object(self.updater, "CONFIG_PATH", path):
                with self.assertRaisesRegex(RuntimeError, "relink/recovery required"):
                    self.updater._load_persistent_identity()

    def test_updater_rejects_stale_pairing_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self._config(Path(temporary), pairing_token="cap_pair_example")
            with mock.patch.object(self.updater, "CONFIG_PATH", path):
                with self.assertRaisesRegex(RuntimeError, "pairing_token"):
                    self.updater._load_persistent_identity()

    def test_post_update_heartbeat_must_be_new_and_match_agent(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "agent-runtime.log"
            log.write_text(
                "2026-09-01T20:00:00Z INFO heartbeat ok agent=agent-old health=online status=active\n",
                encoding="utf-8",
            )
            with mock.patch.object(self.updater, "AGENT_LOG", log):
                checkpoint = self.updater._log_checkpoint()
                self.assertFalse(self.updater._heartbeat_ok_since(checkpoint, "agent-target"))
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(
                        "2026-09-01T20:01:00Z INFO heartbeat ok agent=agent-target health=online status=active\n"
                    )
                self.assertTrue(self.updater._heartbeat_ok_since(checkpoint, "agent-target"))
                self.assertFalse(self.updater._heartbeat_ok_since(checkpoint, "agent-other"))

    def test_installer_refuses_existing_agent_config_before_installation(self):
        text = INSTALLER_PATH.read_text(encoding="utf-8")
        guard = 'if [[ -e "${CONFIG_PATH}" || -L "${CONFIG_PATH}" ]]; then'
        self.assertIn(guard, text)
        self.assertIn("O instalador recusou sobrescrever a identidade persistida do Agent", text)
        self.assertLess(text.index(guard), text.index("install_runtime_dependencies\n"))
        self.assertIn("Use o updater para atualização", text)
        self.assertIn("fluxo administrativo de relink", text)


if __name__ == "__main__":
    unittest.main()
