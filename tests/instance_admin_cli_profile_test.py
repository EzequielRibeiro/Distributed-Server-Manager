#!/usr/bin/env python3
"""Contract resource profile must match queued CLI provisioning policy."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from instance_admin_cli import _contract_profile_configuration


class InstanceAdminCliProfileTest(unittest.TestCase):
    def setUp(self):
        self.contracts = [{
            "id": "contract-minecraft", "game_id": "minecraft",
            "status": "active", "resource_profile_id": "low",
        }]

    def test_cli_provisioning_inherits_low_profile_and_contract_allowlist(self):
        config = _contract_profile_configuration(
            self.contracts, "contract-minecraft", "minecraft",
            {"runtime_definition_id": "minecraft.java.vanilla"},
        )
        self.assertEqual(config["resource_profile_id"], "low")
        self.assertEqual(config["allowed_resource_profiles"], ["low"])

    def test_cli_rejects_foreign_inactive_and_wrong_game_contracts(self):
        cases = [
            (self.contracts, "other", "minecraft"),
            (self.contracts, "contract-minecraft", "dayz"),
            ([dict(self.contracts[0], status="inactive")], "contract-minecraft", "minecraft"),
        ]
        for contracts, cid, game in cases:
            with self.subTest(cid=cid, game=game):
                with self.assertRaises(PermissionError):
                    _contract_profile_configuration(contracts, cid, game, {})

    def test_unrestricted_contract_keeps_catalog_default_selection(self):
        contracts = [dict(self.contracts[0], resource_profile_id=None)]
        self.assertEqual(
            _contract_profile_configuration(contracts, "contract-minecraft", "minecraft",
                                            {"runtime_definition_id": "minecraft.java.vanilla"}),
            {"runtime_definition_id": "minecraft.java.vanilla"},
        )


if __name__ == "__main__":
    unittest.main()
