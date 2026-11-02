#!/usr/bin/env python3
"""Issue #977: both update pipelines must report DayZ DLC preflight evidence."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "linux" / "runtime"))

from dayz_update_content_preflight import inspect_update_content_preflight


class DayZUpdateContentPreflightTest(unittest.TestCase):
    def make_dlc(self, root: Path):
        addons = root / "nasdara" / "addons"
        addons.mkdir(parents=True)
        (addons / "ai_nasdara.pbo").write_bytes(b"synthetic")
        return addons

    def test_matching_owner_reports_no_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_dlc(root)
            # The module's default runtime identity may differ on CI;
            # here test the stable structure, not host-specific ownership.
            from unittest.mock import patch
            from content_discovery_audit import audit_dayz_dlc_roots
            with patch("dayz_update_content_preflight.audit_dayz_dlc_roots",
                       side_effect=lambda root, runtime_user: audit_dayz_dlc_roots(root, expected_uid=os.getuid())):
                result = inspect_update_content_preflight(root, "dayz")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["dlc_package_count"], 1)
            self.assertFalse(result["requires_review"])
            self.assertFalse(result["repair_performed"])
            self.assertTrue(result["read_only"])

    def test_non_dayz_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            self.make_dlc(Path(td))
            for game in ("minecraft", "palworld", "fivem"):
                self.assertIsNone(inspect_update_content_preflight(Path(td), game))

    def test_unavailable_content_is_review_not_success(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "nasdara").mkdir()
            result = inspect_update_content_preflight(Path(td), "dayz")
            self.assertEqual(result["status"], "unknown")
            self.assertTrue(result["requires_review"])
            self.assertFalse(result["repair_performed"])

    def test_both_update_paths_have_pre_activation_hook(self):
        """Contract: no update path should omit this read-only check."""
        normal = (ROOT / "agents/linux/runtime/server_update_agent.py").read_text()
        maintenance = (ROOT / "agents/linux/runtime/maintenance_game_update.py").read_text()
        self.assertIn("content_preflight = inspect_update_content_preflight(staging, game)", normal)
        self.assertIn("content_preflight=inspect_update_content_preflight(staging,game)", maintenance)
        self.assertLess(normal.index("content_preflight = inspect_update_content_preflight(staging, game)"),
                        normal.index("previous = activate(target, staging)"))
        self.assertLess(maintenance.index("content_preflight=inspect_update_content_preflight(staging,game)"),
                        maintenance.index("previous=activate(target,staging)"))
        self.assertIn('"content_discovery_preflight": content_preflight', normal)
        self.assertIn('"content_discovery_preflight":content_preflight', maintenance)


if __name__ == "__main__":
    unittest.main()
