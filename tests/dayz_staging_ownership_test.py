#!/usr/bin/env python3
"""Tests for opt-in, FD-scoped DayZ staging ownership normalizer (#977)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.linux.runtime.dayz_staging_ownership import (
    StagingOwnershipError, plan_or_normalize_dayz_staging,
)

STAGE = ".serverfiles.capivara-update-staging-" + "a" * 32


class DayZStagingOwnershipTest(unittest.TestCase):
    def create_stage(self, root: Path, *, dlc: str = "nasdara") -> Path:
        staging = root / STAGE
        addon = staging / dlc / "addons"
        addon.mkdir(parents=True)
        (addon / "ai_nasdara.pbo").write_bytes(b"pbo-data")
        return staging

    def test_dry_run_does_not_modify_ownership(self):
        with tempfile.TemporaryDirectory() as td:
            stage = self.create_stage(Path(td))
            file = stage / "nasdara/addons/ai_nasdara.pbo"
            before = file.stat()
            with patch("agents.linux.runtime.dayz_staging_ownership.os.fchown") as chown:
                result = plan_or_normalize_dayz_staging(
                    stage, target_uid=before.st_uid + 10, target_gid=before.st_gid + 10,
                )
                chown.assert_not_called()
            self.assertEqual(result["mode"], "dry-run")
            self.assertEqual(result["candidate_count"], 3)
            self.assertEqual(file.stat().st_uid, before.st_uid)

    def test_arbitrary_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            plain = Path(td) / "production"
            plain.mkdir()
            with self.assertRaisesRegex(StagingOwnershipError, "not_transaction_staging"):
                plan_or_normalize_dayz_staging(plain, target_uid=123, target_gid=123)

    def test_apply_must_be_explicitly_authorized(self):
        with tempfile.TemporaryDirectory() as td:
            stage = self.create_stage(Path(td))
            with self.assertRaisesRegex(StagingOwnershipError, "explicit_authorization_required"):
                plan_or_normalize_dayz_staging(stage, target_uid=99, target_gid=99, apply=True)

    def test_apply_needs_privileged_agent_even_with_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            stage = self.create_stage(Path(td))
            with patch("agents.linux.runtime.dayz_staging_ownership.os.geteuid", return_value=1000):
                with self.assertRaisesRegex(StagingOwnershipError, "privileged_agent_required"):
                    plan_or_normalize_dayz_staging(stage, target_uid=99, target_gid=99,
                                                  apply=True, authorized=True)

    def test_authorized_apply_calls_fd_scoped_chown_only(self):
        with tempfile.TemporaryDirectory() as td:
            stage = self.create_stage(Path(td))
            with patch("agents.linux.runtime.dayz_staging_ownership.os.geteuid", return_value=0):
                with patch("agents.linux.runtime.dayz_staging_ownership.os.fchown") as chown:
                    result = plan_or_normalize_dayz_staging(stage, target_uid=88888,
                                                            target_gid=88888, apply=True,
                                                            authorized=True)
            self.assertTrue(result["applied"])
            self.assertTrue(result["transaction_activation_required"])
            self.assertEqual(result["modified_count"], 3)
            self.assertEqual(chown.call_count, 3)

    def test_midway_failure_rolls_back_prior_fds(self):
        with tempfile.TemporaryDirectory() as td:
            stage = self.create_stage(Path(td))
            calls = []
            def changer(fd, uid, gid):
                calls.append((fd, uid, gid))
                if len(calls) == 2:
                    raise OSError("simulated fchown error")
            with patch("agents.linux.runtime.dayz_staging_ownership.os.geteuid", return_value=0):
                with patch("agents.linux.runtime.dayz_staging_ownership.os.fchown", side_effect=changer):
                    with self.assertRaisesRegex(StagingOwnershipError, "normalization_failed_rolled_back"):
                        plan_or_normalize_dayz_staging(stage, target_uid=88888, target_gid=88888,
                                                      apply=True, authorized=True)
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[-1][1], os.getuid())

    def test_symlinked_dlc_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            stage = self.create_stage(Path(td))
            (stage / "nasdara/addons/unsafe.bin").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(StagingOwnershipError, "symlink_in_addons"):
                plan_or_normalize_dayz_staging(stage, target_uid=88888, target_gid=88888)

    def test_hardlink_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            stage = self.create_stage(Path(td))
            package = stage / "nasdara/addons/ai_nasdara.pbo"
            os.link(package, Path(td) / "outside.pbo")
            with self.assertRaisesRegex(StagingOwnershipError, "unsafe_package_inode"):
                plan_or_normalize_dayz_staging(stage, target_uid=88888, target_gid=88888)

    def test_missing_package_prevents_changes(self):
        with tempfile.TemporaryDirectory() as td:
            stage = self.create_stage(Path(td))
            (stage / "nasdara/addons/ai_nasdara.pbo").unlink()
            with self.assertRaisesRegex(StagingOwnershipError, "known_dlc_without_packages"):
                plan_or_normalize_dayz_staging(stage, target_uid=88888, target_gid=88888)

    def test_other_game_files_remain_outside_scope(self):
        with tempfile.TemporaryDirectory() as td:
            stage = self.create_stage(Path(td))
            another = stage / "minecraft/addons"
            another.mkdir(parents=True)
            (another / "world.pbo").write_bytes(b"test")
            r = plan_or_normalize_dayz_staging(stage, target_uid=88888, target_gid=88888)
            self.assertTrue(all(x["path"].startswith("nasdara/") or x["path"] == "nasdara"
                                for x in r["candidates"]))

if __name__ == "__main__":
    unittest.main()
