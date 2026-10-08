#!/usr/bin/env python3
"""Contract tests for future transactional NeoForge + Server Pack migration."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

VALID = {
    "kind": "MinecraftServerPackMigration",
    "schema_version": 1,
    "instance_id": "cli-000001-minecraft-005",
    "content_id": "atm11",
    "transfer_id": "transfer-abc123",
    "filename": "ServerFiles-0.9.0-beta.zip",
    "archive_sha256": "a" * 64,
    "archive_size_bytes": 518936896,
    "serverpack_prefix": "",
    "serverpack_mod_count": 254,
    "serverpack_override_dirs": ["config", "kubejs"],
    "migration_plan_sha256": "b" * 64,
    "previous_bundle_revision": 2,
    "previous_manifest_sha256": "c" * 64,
    "from_loader_version": "26.1.2.94",
    "target_loader_version": "26.1.2.109",
    "minecraft_version": "26.1.2",
    "isolated_install_dir": "instance-abc123-def456",
    "backup_before_update": True,
    "preserve_world": True,
    "install_allowed": False,
}


def load(platform: str):
    path = ROOT / "agents" / platform / "runtime" / "minecraft_serverpack_migration_contract.py"
    spec = importlib.util.spec_from_file_location(f"migration_contract_{platform}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class MinecraftServerPackMigrationContractTest(unittest.TestCase):
    def test_linux_and_windows_contracts_are_identical(self):
        linux=(ROOT/"agents/linux/runtime/minecraft_serverpack_migration_contract.py").read_bytes()
        windows=(ROOT/"agents/windows/runtime/minecraft_serverpack_migration_contract.py").read_bytes()
        self.assertEqual(linux,windows)

    def test_valid_current_to_newer_loader_evidence_normalizes(self):
        for platform in ("linux","windows"):
            with self.subTest(platform=platform):
                module=load(platform)
                result=module.validate_minecraft_serverpack_migration(
                    dict(VALID), instance_id=VALID["instance_id"])
                self.assertEqual(result["target_loader_version"],"26.1.2.109")
                self.assertEqual(result["archive_size_bytes"],518936896)
                self.assertFalse(result["install_allowed"])

    def test_identity_path_and_hash_injection_are_rejected(self):
        mutations=(
            {"instance_id":"other-instance"},
            {"filename":"../ServerFiles.zip"},
            {"archive_sha256":"not-a-sha"},
            {"migration_plan_sha256":"d"*63},
            {"previous_manifest_sha256":""},
            {"isolated_install_dir":"../runtime"},
            {"transfer_id":"bad/transfer"},
            {"content_id":"bad/content"},
        )
        for platform in ("linux","windows"):
            module=load(platform)
            for mutation in mutations:
                with self.subTest(platform=platform,mutation=mutation):
                    body={**VALID,**mutation}
                    with self.assertRaises(module.MinecraftServerPackMigrationContractError):
                        module.validate_minecraft_serverpack_migration(
                            body, instance_id=VALID["instance_id"])

    def test_downgrade_same_build_and_missing_safety_flags_are_rejected(self):
        mutations=(
            {"target_loader_version":"26.1.2.94"},
            {"target_loader_version":"26.1.2.93"},
            {"backup_before_update":False},
            {"preserve_world":False},
            {"install_allowed":True},
            {"previous_bundle_revision":0},
            {"archive_size_bytes":0},
            {"schema_version":2},
        )
        for platform in ("linux","windows"):
            module=load(platform)
            for mutation in mutations:
                with self.subTest(platform=platform,mutation=mutation):
                    with self.assertRaises(module.MinecraftServerPackMigrationContractError):
                        module.validate_minecraft_serverpack_migration(
                            {**VALID,**mutation}, instance_id=VALID["instance_id"])

    def test_unknown_fields_are_rejected(self):
        for platform in ("linux","windows"):
            module=load(platform)
            with self.subTest(platform=platform):
                with self.assertRaisesRegex(
                    module.MinecraftServerPackMigrationContractError,
                    "unsupported migration fields",
                ):
                    module.validate_minecraft_serverpack_migration(
                        {**VALID,"shell":"rm -rf /"},instance_id=VALID["instance_id"])


if __name__=="__main__":
    unittest.main()
