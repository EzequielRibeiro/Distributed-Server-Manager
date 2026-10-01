#!/usr/bin/env python3
"""Storage and evidence guards for future staged NeoForge + Server Pack updates."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from minecraft_staged_migration_safety import (
    StagedMigrationSafetyError, assess_staged_migration,
)

GiB = 1024**3
BACKUP = {"backup_id": "test-backup", "sha256": "a"*64, "integrity_verified": True}
PLAN = {"migration_plan_sha256": "b"*64, "install_allowed": False}


def budget(**overrides):
    params = dict(
        available_bytes=32*GiB,
        backup_bytes=5*GiB,
        serverpack_zip_bytes=1*GiB,
        expanded_pack_bytes=2*GiB,
        new_runtime_bytes=1*GiB,
        backup_evidence=BACKUP,
        plan_evidence=PLAN,
        required_headroom_bytes=2*GiB,
    )
    params.update(overrides)
    return assess_staged_migration(**params)


class MigrationCapacityAssessmentTest(unittest.TestCase):
    def test_capacity_estimate_preserves_rollback_and_new_backup_room(self):
        result = budget()
        self.assertEqual(result["required_bytes"], 16*GiB)
        self.assertTrue(result["sufficient"])
        self.assertFalse(result["install_allowed"])
        self.assertTrue(result["requires_exclusive_recheck"])

    def test_undersized_disk_reports_shortfall_not_permission(self):
        result = budget(available_bytes=6*GiB)
        self.assertFalse(result["sufficient"])
        self.assertEqual(result["shortfall_bytes"], 10*GiB)
        self.assertFalse(result["install_allowed"])

    def test_unverified_backup_is_rejected(self):
        for evidence in (
            {"backup_id":"test","sha256":"a"*64,"integrity_verified":False},
            {"backup_id":"test","sha256":"not-sha","integrity_verified":True},
            {"backup_id":"","sha256":"a"*64,"integrity_verified":True},
        ):
            with self.subTest(evidence=evidence):
                with self.assertRaises(StagedMigrationSafetyError):
                    budget(backup_evidence=evidence)

    def test_missing_or_executable_plan_is_rejected(self):
        for evidence in ({}, {"migration_plan_sha256":"b"*64,"install_allowed":True},
                         {"migration_plan_sha256":"b"*64}):
            with self.subTest(evidence=evidence):
                with self.assertRaises(StagedMigrationSafetyError):
                    budget(plan_evidence=evidence)

    def test_unknown_or_zero_sizes_fail_closed(self):
        for key,value in (("backup_bytes",0), ("new_runtime_bytes",-1),
                          ("expanded_pack_bytes",None),("available_bytes",True)):
            with self.subTest(key=key):
                with self.assertRaises(StagedMigrationSafetyError):
                    budget(**{key:value})


    def test_both_agents_reject_staged_migration_before_side_effects(self):
        for os_name in ("linux","windows"):
            with self.subTest(os_name=os_name):
                code = (ROOT / "agents" / os_name / "runtime" / "provisioning_executor.py").read_text(encoding="utf-8")
                self.assertIn('if "minecraft_serverpack_migration" in configuration:', code)
                rejection = code.index("staged Minecraft loader and Server Pack migration executor is not yet homologated")
                self.assertLess(rejection, code.index('step = "install_content"'))
                self.assertLess(rejection, code.index("create_backup("))


if __name__ == "__main__":
    unittest.main()
