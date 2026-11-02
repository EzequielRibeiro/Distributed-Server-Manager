#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "linux" / "runtime"))
from content_repair_plan import plan_dayz_dlc_ownership


class DayZContentRepairPlanTest(unittest.TestCase):
    def make_dlc(self, root: Path, name="nasdara"):
        p = root / name / "addons"
        p.mkdir(parents=True)
        (p / "ai_nasdara.pbo").write_bytes(b"test")
        return p

    def test_dry_run_exposes_bounded_metadata_without_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = self.make_dlc(root)
            original = (p / "ai_nasdara.pbo").stat()
            plan = plan_dayz_dlc_ownership(root, expected_uid=os.getuid() + 1)
            self.assertEqual(plan["status"], "review_required")
            self.assertFalse(plan["executable"])
            self.assertTrue(plan["read_only"])
            self.assertEqual(len(plan["candidates"]), 3)
            self.assertEqual((p / "ai_nasdara.pbo").stat().st_uid, original.st_uid)
            self.assertNotIn("command", str(plan).lower())

    def test_correct_owner_needs_no_changes(self):
        with tempfile.TemporaryDirectory() as td:
            self.make_dlc(Path(td))
            plan = plan_dayz_dlc_ownership(Path(td), expected_uid=os.getuid())
            self.assertEqual(plan["status"], "no_owner_mismatch")
            self.assertEqual(plan["candidates"], [])

    def test_unknown_dlc_root_never_planned(self):
        with tempfile.TemporaryDirectory() as td:
            self.make_dlc(Path(td), "arbitrary")
            self.assertEqual(plan_dayz_dlc_ownership(Path(td), expected_uid=os.getuid() + 1)["status"], "blocked")

    def test_missing_known_dlc_packages_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "nasdara" / "addons").mkdir(parents=True)
            self.assertEqual(plan_dayz_dlc_ownership(Path(td), expected_uid=os.getuid())["status"], "blocked")

    def test_symlinked_dlc_blocks(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as external:
            root = Path(td)
            self.make_dlc(Path(external))
            (root / "nasdara").symlink_to(Path(external) / "nasdara", target_is_directory=True)
            self.assertEqual(plan_dayz_dlc_ownership(root, expected_uid=os.getuid())["status"], "blocked")

    def test_unrelated_folders_never_planned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_dlc(root)
            self.make_dlc(root, "mods")
            p = plan_dayz_dlc_ownership(root, expected_uid=os.getuid() + 1)
            self.assertTrue(all(x["relative_path"].startswith("nasdara/") or x["relative_path"] == "nasdara" for x in p["candidates"]))

    def test_unexpected_directory_change_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            self.make_dlc(Path(td))
            with patch("content_repair_plan.MAX_PLAN_ENTRIES", 1):
                p = plan_dayz_dlc_ownership(Path(td), expected_uid=os.getuid() + 1)
            self.assertEqual(p["status"], "blocked")
            self.assertEqual(p["candidates"], [])


if __name__ == "__main__":
    unittest.main()
