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
from content_discovery_audit import audit_dayz_dlc_roots
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

    def test_symlink_to_external_dlc_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external:
            root = Path(tmp)
            target = self._make_dlc(Path(external), "secret").parent
            (root / "nasdara").symlink_to(target, target_is_directory=True)
            result = audit_dayz_dlc_roots(root, expected_uid=os.getuid())
            self.assertEqual(result["status"], "unsafe")

    def test_symlink_in_dlc_addons_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addon = self._make_dlc(root, "nasdara")
            (addon / "link.pbo").symlink_to("/etc/passwd")
            self.assertEqual(audit_dayz_dlc_roots(root, expected_uid=os.getuid())["status"], "unsafe")


if __name__ == "__main__":
    unittest.main()
