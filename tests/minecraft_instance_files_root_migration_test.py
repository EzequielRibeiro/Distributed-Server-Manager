#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for value in (str(ROOT), str(RUNTIME)):
    if value not in sys.path:
        sys.path.insert(0, value)

import game_runtime
import instance_runtime
import provisioning_state


class MinecraftInstanceFilesRootMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.old_state = instance_runtime.STATE_DIR
        self.old_history = provisioning_state.HISTORY_ROOT
        instance_runtime.STATE_DIR = self.root / "agent-state"
        provisioning_state.HISTORY_ROOT = self.root / "history"
        self.config = {"agent_id": "agent-one"}

    def tearDown(self):
        instance_runtime.STATE_DIR = self.old_state
        provisioning_state.HISTORY_ROOT = self.old_history
        self.temp.cleanup()

    def java_context(self, runtime_id: str) -> dict:
        install = self.root / "game-data" / runtime_id
        install.mkdir(parents=True, exist_ok=True)
        state = self.root / "instances" / "minecraft-java"
        return {
            "install_path": str(install),
            "content_root": str(install),
            "instance_state_root": str(state),
            "ports": {
                "game": {"port": 25565, "protocol": "tcp"},
                "rcon": {"port": 25566, "protocol": "tcp"},
                "query": {"port": 25567, "protocol": "udp"},
                "votifier": {"port": 25568, "protocol": "tcp"},
            },
            "catalog_runtime_policy": {
                "runtime_id": runtime_id,
                "engine": "java",
            },
            "catalog_content_policy": {"managed": {}},
            "environment": {},
        }

    def test_java_v1_record_migrates_file_browser_to_private_runtime_tree(self):
        runtime_id = "minecraft.java.paper"
        spec = game_runtime.build_runtime_spec(
            self.config,
            {
                "instance_id": "minecraft-java",
                "agent_id": "agent-one",
                "game_id": "minecraft",
                "environment_id": runtime_id,
                "runtime_id": runtime_id,
                "desired_state": "running",
            },
            self.java_context(runtime_id),
        )
        legacy = dict(spec)
        legacy["profile_version"] = 1
        legacy.pop("files_root", None)

        migrated, changed = game_runtime.migrate_runtime_spec(self.config, legacy)

        self.assertTrue(changed)
        self.assertEqual(migrated["profile_version"], 3)
        self.assertEqual(migrated["profile_migrated_from_version"], 1)
        self.assertEqual(migrated["files_root"], migrated["working_directory"])
        self.assertEqual(
            Path(migrated["files_root"]),
            Path(migrated["instance_state_root"]) / "runtime",
        )
        self.assertNotEqual(
            Path(migrated["files_root"]),
            Path(migrated["instance_state_root"]),
        )

    def test_bedrock_v1_record_migrates_file_browser_to_private_runtime_tree(self):
        runtime_id = "minecraft.bedrock.vanilla"
        install = self.root / "game-data" / "bedrock"
        install.mkdir(parents=True, exist_ok=True)
        state = self.root / "instances" / "minecraft-bedrock"
        spec = game_runtime.build_runtime_spec(
            self.config,
            {
                "instance_id": "minecraft-bedrock",
                "agent_id": "agent-one",
                "game_id": "minecraft",
                "environment_id": runtime_id,
                "runtime_id": runtime_id,
                "desired_state": "stopped",
            },
            {
                "install_path": str(install),
                "content_root": str(install),
                "instance_state_root": str(state),
                "ports": {
                    "game_ipv4": {"port": 19132, "protocol": "udp"},
                    "game_ipv6": {"port": 19133, "protocol": "udp"},
                },
                "catalog_runtime_policy": {
                    "runtime_id": runtime_id,
                    "engine": "native",
                },
                "environment": {},
            },
        )
        legacy = dict(spec)
        legacy["profile_version"] = 1
        legacy.pop("files_root", None)

        migrated, changed = game_runtime.migrate_runtime_spec(self.config, legacy)

        self.assertTrue(changed)
        self.assertEqual(migrated["profile_version"], 2)
        self.assertEqual(migrated["files_root"], migrated["working_directory"])
        self.assertEqual(
            Path(migrated["files_root"]),
            Path(migrated["instance_state_root"]) / "runtime",
        )


if __name__ == "__main__":
    unittest.main()
