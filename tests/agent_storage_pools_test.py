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
import storage_pools


class AgentStoragePoolsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_state = instance_runtime.STATE_DIR
        instance_runtime.STATE_DIR = self.root / "agent-state"
        instance_runtime.STATE_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        instance_runtime.STATE_DIR = self.old_state
        self.temp.cleanup()

    def config(self):
        return {
            "agent_id": "agent-one",
            "storage_pools": [
                {
                    "id": "nvme",
                    "name": "NVMe principal",
                    "root_path": str(self.root / "nvme"),
                    "storage_class": "nvme",
                    "enabled": True,
                    "priority": 100,
                    "reserve_bytes": 1024,
                },
                {
                    "id": "hdd",
                    "root_path": str(self.root / "hdd"),
                    "storage_class": "capacity",
                    "enabled": True,
                    "priority": 10,
                },
            ],
            "default_storage_pool_id": "nvme",
        }

    def test_legacy_root_becomes_default_pool(self):
        legacy = {"instance_storage_root": str(self.root / "legacy")}
        pools = storage_pools.storage_pools(legacy)
        self.assertEqual(len(pools), 1)
        self.assertEqual(pools[0]["id"], "default")
        self.assertTrue(pools[0]["legacy"])
        self.assertEqual(storage_pools.default_storage_pool_id(legacy), "default")

    def test_multiple_pools_require_or_resolve_default(self):
        config = self.config()
        self.assertEqual(storage_pools.default_storage_pool_id(config), "nvme")
        self.assertEqual(storage_pools.resolve_storage_pool(config, "hdd")["storage_class"], "capacity")
        broken = dict(config)
        broken.pop("default_storage_pool_id")
        with self.assertRaisesRegex(ValueError, "default_storage_pool_id"):
            storage_pools.default_storage_pool_id(broken)

    def test_duplicate_roots_are_rejected(self):
        config = self.config()
        config["storage_pools"][1]["root_path"] = config["storage_pools"][0]["root_path"]
        with self.assertRaisesRegex(ValueError, "duplicate storage pool root"):
            storage_pools.storage_pools(config)

    def test_disabled_pool_cannot_be_selected(self):
        config = self.config()
        config["storage_pools"][1]["enabled"] = False
        with self.assertRaisesRegex(ValueError, "disabled"):
            storage_pools.resolve_storage_pool(config, "hdd")

    def test_instance_state_root_is_derived_from_selected_pool(self):
        config = self.config()
        state = game_runtime.instance_state_root(config, "dayz-one", "hdd")
        self.assertEqual(state, (self.root / "hdd" / "dayz-one").resolve())

    def test_runtime_spec_persists_storage_pool_identity(self):
        config = self.config()
        install = self.root / "serverfiles"
        install.mkdir()
        instance = {
            "instance_id": "dayz-one",
            "agent_id": "agent-one",
            "game_id": "dayz",
            "environment_id": "dayz.stable",
            "desired_state": "stopped",
            "storage_pool_id": "hdd",
        }
        context = {
            "install_path": str(install),
            "ports": {
                "game": {"port": 24010, "protocol": "udp"},
                "game_aux": {"port": 24012, "protocol": "udp"},
                "steam_query": {"port": 24013, "protocol": "udp"},
            },
        }
        spec = game_runtime.build_runtime_spec(config, instance, context)
        self.assertEqual(spec["storage_pool_id"], "hdd")
        self.assertEqual(Path(spec["instance_state_root"]), (self.root / "hdd" / "dayz-one").resolve())
        self.assertEqual(spec["profile_context"]["storage_pool_id"], "hdd")

    def test_privileged_helper_resolves_pool_from_local_config(self):
        module_path = ROOT / "agents" / "linux" / "privileged" / "materialize_instance.py"
        module_spec = importlib.util.spec_from_file_location("capivara_storage_pool_materializer", module_path)
        module = importlib.util.module_from_spec(module_spec)
        assert module_spec.loader is not None
        module_spec.loader.exec_module(module)
        config = self.config()
        self.assertEqual(module._instance_storage_root(config, "nvme"), (self.root / "nvme").resolve())
        self.assertEqual(module._instance_storage_root(config, "hdd"), (self.root / "hdd").resolve())


if __name__ == "__main__":
    unittest.main()
