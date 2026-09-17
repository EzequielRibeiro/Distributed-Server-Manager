#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from baseline_upgrade_engine import UPGRADES, latest_upgrade_version


class BaselineV12V13RegistryTest(unittest.TestCase):
    def test_registry_is_contiguous_through_v13(self) -> None:
        self.assertEqual([upgrade.version for upgrade in UPGRADES], list(range(1, 14)))
        self.assertEqual(latest_upgrade_version(), 13)
        self.assertEqual(UPGRADES[-2].name, "universal_content_update")
        self.assertEqual(UPGRADES[-1].name, "maintenance_restart_framework")


if __name__ == "__main__":
    unittest.main()
