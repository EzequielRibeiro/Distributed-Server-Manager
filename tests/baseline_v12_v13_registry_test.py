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


class BaselineV12V20RegistryTest(unittest.TestCase):
    def test_registry_is_contiguous_through_v20(self) -> None:
        self.assertEqual([upgrade.version for upgrade in UPGRADES], list(range(1, 21)))
        self.assertEqual(latest_upgrade_version(), 20)
        self.assertEqual(UPGRADES[-9].name, "universal_content_update")
        self.assertEqual(UPGRADES[-8].name, "maintenance_restart_framework")
        self.assertEqual(UPGRADES[-7].name, "yarax_admin_operations")
        self.assertEqual(UPGRADES[-6].name, "dayz_native_restart_commands")
        self.assertEqual(UPGRADES[-5].name, "generic_native_restart_commands")
        self.assertEqual(UPGRADES[-4].name, "database_intelligence")
        self.assertEqual(UPGRADES[-3].name, "operation_diagnostics")
        self.assertEqual(UPGRADES[-2].name, "alert_customer_identity")
        self.assertEqual(UPGRADES[-1].name, "legacy_minecraft_contract_products")


if __name__ == "__main__":
    unittest.main()
