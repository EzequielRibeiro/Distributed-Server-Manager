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


class BaselineV12V23RegistryTest(unittest.TestCase):
    def test_registry_is_contiguous_through_v23(self) -> None:
        self.assertEqual([upgrade.version for upgrade in UPGRADES], list(range(1, 24)))
        self.assertEqual(latest_upgrade_version(), 23)
        expected = (
            "universal_content_update", "maintenance_restart_framework",
            "yarax_admin_operations", "dayz_native_restart_commands",
            "generic_native_restart_commands", "database_intelligence",
            "operation_diagnostics", "alert_customer_identity",
            "legacy_minecraft_contract_products", "dayz_management_operations",
            "instance_evidence_parameters", "instance_agent_relocation",
        )
        self.assertEqual(tuple(upgrade.name for upgrade in UPGRADES[-12:]), expected)


if __name__ == "__main__":
    unittest.main()
