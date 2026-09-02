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

IDENTITY_FIELDS = (
    "controller_url",
    "agent_id",
    "node_id",
    "fingerprint",
    "credential_id",
    "credential_secret",
)


def _load_updater():
    spec = importlib.util.spec_from_file_location("capivara_agent_lifecycle_gate", UPDATER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentLifecycleIntegrityGateTest(unittest.TestCase):
    """Regression gate for Agent identity/update/readiness integrity.

    This is intentionally independent from game-specific provisioning. The generic
    multi-game E2E gate may rely on these invariants before testing any runtime:
    persistent identity is enrollment state, updates do not own that state, and a
    restarted Agent is not considered ready until the Controller accepts a fresh
    heartbeat from the same logical Agent.
    """

    def setUp(self):
        self.updater = _load_updater()

    @staticmethod
    def _identity(**changes):
        payload = {
            "controller_url": "https://controller.example:9443",
            "agent_id": "agent-0123456789abcdef0123",
            "node_id": "node-0123456789abcdef0123",
            "fingerprint": "sha256:" + "a" * 64,
            "credential_id": "cred-0123456789abcdef0123456789abcdef",
            "credential_secret": "test-secret-not-real",
        }
        payload.update(changes)
        return payload

    def test_persistent_identity_contract_contains_all_stable_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "agent.json"
            config.write_text(json.dumps(self._identity()), encoding="utf-8")
            with mock.patch.object(self.updater, "CONFIG_PATH", config):
                loaded = self.updater._load_persistent_identity()

        for field in IDENTITY_FIELDS:
            self.assertTrue(str(loaded.get(field) or "").strip(), field)
        self.assertFalse(str(loaded.get("pairing_token") or "").strip())

    def test_update_payload_mapping_never_targets_persistent_agent_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "package"
            (package_root / "agent/runtime").mkdir(parents=True)
            (package_root / "agent/runtime/agent.py").write_text("pass\n", encoding="utf-8")

            install_root = Path(temporary) / "installed"
            config_path = Path(temporary) / "etc/capivara-agent/agent.json"
            with (
                mock.patch.object(self.updater, "INSTALL_ROOT", install_root),
                mock.patch.object(self.updater, "CONFIG_PATH", config_path),
                mock.patch.object(self.updater, "POLKIT_RULES_DIR", Path(temporary) / "polkit"),
                mock.patch.object(self.updater, "SYSTEMD_DIR", Path(temporary) / "systemd"),
            ):
                destinations = [destination for _, destination, _, _ in self.updater._mapping(package_root)]

        self.assertNotIn(config_path, destinations)
        self.assertTrue(any(path.name == "agent.py" for path in destinations))

    def test_installer_cannot_be_used_as_an_update_path(self):
        text = INSTALLER_PATH.read_text(encoding="utf-8")
        guard = 'if [[ -e "${CONFIG_PATH}" || -L "${CONFIG_PATH}" ]]; then'
        self.assertIn(guard, text)
        self.assertIn("O instalador recusou sobrescrever a identidade persistida do Agent", text)
        self.assertIn("Use o updater para atualização", text)
        self.assertIn("fluxo administrativo de relink", text)

    def test_post_update_readiness_requires_fresh_matching_heartbeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "agent-runtime.log"
            log.write_text(
                "2026-09-02T10:00:00Z INFO heartbeat ok agent=agent-target health=online status=active\n",
                encoding="utf-8",
            )
            with mock.patch.object(self.updater, "AGENT_LOG", log):
                checkpoint = self.updater._log_checkpoint()

                # A heartbeat that predates the update cannot satisfy readiness.
                self.assertFalse(self.updater._heartbeat_ok_since(checkpoint, "agent-target"))

                # A fresh heartbeat from another logical Agent cannot satisfy it either.
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(
                        "2026-09-02T10:00:01Z INFO heartbeat ok agent=agent-other health=online status=active\n"
                    )
                self.assertFalse(self.updater._heartbeat_ok_since(checkpoint, "agent-target"))

                # Readiness becomes true only for a fresh accepted heartbeat from the
                # same Agent identity that entered the update transaction.
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(
                        "2026-09-02T10:00:02Z INFO heartbeat ok agent=agent-target health=online status=active\n"
                    )
                self.assertTrue(self.updater._heartbeat_ok_since(checkpoint, "agent-target"))

    def test_update_flow_binds_restart_readiness_to_preupdate_agent_id(self):
        text = UPDATER_PATH.read_text(encoding="utf-8")
        self.assertIn('identity = _load_persistent_identity()', text)
        self.assertIn('expected_agent_id = str(identity["agent_id"])', text)
        self.assertIn('_restart_agent(expected_agent_id)', text)


if __name__ == "__main__":
    unittest.main()
