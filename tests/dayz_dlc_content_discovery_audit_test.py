#!/usr/bin/env python3
"""Regression coverage for issue #977's read-only discovery audit."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "linux" / "runtime"))
from content_discovery_audit import MAX_ADDON_ENTRIES, audit_dayz_dlc_roots
from content_repair_plan import plan_dayz_dlc_ownership
from game_data_integrity import inspect_game_data


class DayZDLCDiscoveryAuditTest(unittest.TestCase):
    def _make_dlc(self, root: Path, name: str):
        addon = root / name / "addons"
        addon.mkdir(parents=True)
        (addon / "ai_nasdara.pbo").write_bytes(b"synthetic")
        return addon

    def test_mismatched_owner_is_warning_not_automatic_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addon = self._make_dlc(root, "nasdara")
            before = addon.joinpath("ai_nasdara.pbo").read_bytes()
            actual = os.getuid()
            result = audit_dayz_dlc_roots(root, expected_uid=actual + 10000)
            self.assertEqual(result["status"], "warning")
            self.assertFalse(result["roots"][0]["owner_matches_runner"])
            self.assertEqual(addon.joinpath("ai_nasdara.pbo").read_bytes(), before)

    def test_runner_identity_is_explicit_and_changes_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_dlc(root, "nasdara")
            actual_owner = os.getuid()
            mismatched = audit_dayz_dlc_roots(root, expected_uid=actual_owner + 1)
            correct = audit_dayz_dlc_roots(root, expected_uid=actual_owner)
            self.assertEqual(mismatched["status"], "warning")
            self.assertEqual(correct["status"], "ok")
            self.assertEqual(correct["expected_uid"], actual_owner)

    def test_matching_owner_is_not_a_claim_of_loaded_pbos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_dlc(root, "nasdara")
            result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["roots"][0]["packages"], 1)
            self.assertNotIn("loaded", result)

    def test_package_ownership_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_dlc(root, "nasdara")
            result = audit_dayz_dlc_roots(root, expected_uid=os.getuid() + 123)
            self.assertEqual(result["roots"][0]["package_owner_mismatch_count"], 1)

    def test_integrity_includes_read_only_audit_without_changing_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_dlc(root, "nasdara")
            result = inspect_game_data(root, {"game": "dayz"})
            self.assertEqual(result["health"], "ok")
            self.assertIn(result["content_discovery"]["status"], ("ok", "warning", "unknown"))
            self.assertTrue(result["content_discovery"]["read_only"] if result["content_discovery"]["status"] != "unknown" else True)

    def test_base_and_mod_directories_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_dlc(root, "nasdara")
            self._make_dlc(root, "mods")
            self._make_dlc(root, "addons")
            result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual([p["directory"] for p in result["roots"]], ["nasdara"])

    def test_unrelated_directories_without_addons_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_dlc(root, "nasdara")
            (root / "cache").mkdir()
            (root / "serverfiles.lock").write_bytes(b"x")
            result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual(result["status"], "ok")
            self.assertEqual([r["directory"] for r in result["roots"]], ["nasdara"])

    def test_unrelated_symlink_does_not_block_dlc_audit(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external:
            root = Path(tmp)
            self._make_dlc(root, "sakhal")
            (root / "steam_cache_alias").symlink_to(Path(external), target_is_directory=True)
            result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual(result["status"], "ok")

    def test_known_dlc_missing_addons_is_unknown_not_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "nasdara").mkdir()
            result = audit_dayz_dlc_roots(Path(tmp), expected_uid=os.getuid())
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["reason"], "known_dlc_missing_addons")

    def test_known_dlc_empty_addons_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nasdara" / "addons").mkdir(parents=True)
            result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["reason"], "known_dlc_no_packages")

    def test_unknown_folder_with_empty_addons_is_not_dlc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "some_other_folder" / "addons").mkdir(parents=True)
            result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["roots"], [])

    def test_unrecognized_addons_with_packages_do_not_enter_repair_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_dlc(root, "nasdara")
            self._make_dlc(root, "unrelated_content")
            audit = audit_dayz_dlc_roots(root, expected_uid=os.getuid() + 7)
            plan = plan_dayz_dlc_ownership(root, expected_uid=os.getuid() + 7)
            self.assertEqual([r["directory"] for r in audit["roots"]], ["nasdara"])
            self.assertEqual(audit["status"], "warning")
            self.assertEqual(plan["status"], "review_required")
            self.assertTrue(plan["candidates"])
            self.assertTrue(all(c["relative_path"] == "nasdara" or c["relative_path"].startswith("nasdara/") for c in plan["candidates"]))

    def test_install_root_entry_count_is_bounded(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_dlc(root, "nasdara")
            (root / "other").mkdir()
            with patch("content_discovery_audit.MAX_TOP_LEVEL_ENTRIES", 1):
                result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["reason"], "install_root_entry_limit")

    def test_symlink_to_external_dlc_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external:
            root = Path(tmp)
            target = self._make_dlc(Path(external), "secret").parent
            (root / "nasdara").symlink_to(target, target_is_directory=True)
            result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual(result["status"], "unsafe")

    def test_dlc_inventory_has_bounded_addon_scan(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addon = self._make_dlc(root, "nasdara")
            (addon / "second.pbo").write_bytes(b"data")
            with patch("content_discovery_audit.MAX_ADDON_ENTRIES", 1):
                result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["reason"], "dlc_addon_entry_limit")

    def test_non_dayz_integrity_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_dlc(root, "nasdara")
            for game in ("minecraft", "palworld"):
                report = inspect_game_data(root, {"game": game})
                self.assertNotIn("content_discovery", report)
                self.assertEqual(report["health"], "ok")

    def test_symlink_in_dlc_addons_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addon = self._make_dlc(root, "nasdara")
            (addon / "link.pbo").symlink_to("/etc/passwd")
            self.assertEqual(audit_dayz_dlc_roots(root, expected_uid=os.getuid())["status"], "unsafe")


if __name__ == "__main__":
    unittest.main()
