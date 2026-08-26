#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import game_runtime
import instance_runtime
import provisioning_state


class AgentInstanceStorageRootTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_state = instance_runtime.STATE_DIR
        self.old_history = provisioning_state.HISTORY_ROOT
        instance_runtime.STATE_DIR = self.root / "agent-state"
        provisioning_state.HISTORY_ROOT = self.root / "history"
        self.instance = {
            "instance_id": "dayz-one",
            "agent_id": "agent-one",
            "game_id": "dayz",
            "environment_id": "dayz.stable",
            "desired_state": "stopped",
        }
        self.install = self.root / "serverfiles"
        self.install.mkdir()

    def tearDown(self):
        instance_runtime.STATE_DIR = self.old_state
        provisioning_state.HISTORY_ROOT = self.old_history
        self.temp.cleanup()

    @staticmethod
    def ports():
        return {
            "game": {"port": 24010, "protocol": "udp"},
            "game_aux": {"port": 24012, "protocol": "udp"},
            "steam_query": {"port": 24013, "protocol": "udp"},
        }

    def test_default_storage_root_preserves_legacy_layout(self):
        spec = game_runtime.build_runtime_spec(
            {"agent_id": "agent-one"},
            self.instance,
            {"install_path": str(self.install), "ports": self.ports()},
        )
        self.assertEqual(spec["instance_state_root"], "/var/lib/capivara-instances/dayz-one")
        self.assertEqual(spec["profile_context"]["instance_state_root"], "/var/lib/capivara-instances/dayz-one")

    def test_custom_storage_root_is_applied_per_instance(self):
        storage = self.root / "games"
        config = {"agent_id": "agent-one", "instance_storage_root": str(storage)}
        spec = game_runtime.build_runtime_spec(
            config,
            self.instance,
            {"install_path": str(self.install), "ports": self.ports()},
        )
        expected = storage / "dayz-one"
        self.assertEqual(Path(spec["instance_state_root"]), expected)
        self.assertEqual(Path(spec["config_path"]), expected / "config" / "serverDZ.cfg")
        self.assertEqual(Path(spec["bind_paths"][0]["source"]), expected / "storage_1")

    def test_client_context_cannot_override_agent_storage_policy_during_privileged_validation(self):
        module_path = ROOT / "agents" / "linux" / "privileged" / "materialize_instance.py"
        module_spec = importlib.util.spec_from_file_location("capivara_materialize_instance", module_path)
        module = importlib.util.module_from_spec(module_spec)
        assert module_spec.loader is not None
        module_spec.loader.exec_module(module)
        storage = self.root / "games"
        self.assertEqual(module._instance_storage_root({"instance_storage_root": str(storage)}), storage.resolve())
        with self.assertRaisesRegex(RuntimeError, "absolute path"):
            module._instance_storage_root({"instance_storage_root": "relative/games"})
        with self.assertRaisesRegex(RuntimeError, "filesystem root"):
            module._instance_storage_root({"instance_storage_root": "/"})

    def test_invalid_instance_id_cannot_escape_storage_root(self):
        config = {"agent_id": "agent-one", "instance_storage_root": str(self.root / "games")}
        with self.assertRaisesRegex(ValueError, "invalid instance_id"):
            game_runtime.instance_state_root(config, "../escape")


if __name__ == "__main__":
    unittest.main()
