from __future__ import annotations

import unittest

from core.configuration_precedence import (
    ConfigurationPrecedenceError,
    resolve_configuration_precedence,
    resolve_precedence_document,
)


class ConfigurationPrecedenceTest(unittest.TestCase):
    def test_system_wins_contract_and_customer(self):
        result = resolve_configuration_precedence(
            system={"network": {"port": 2302}},
            contract={"network": {"port": 2402}},
            customer={"network": {"port": 2502}},
        )
        self.assertEqual(result["effective"]["network"]["port"], 2302)
        self.assertEqual(result["provenance"]["network"]["port"], "SYSTEM")

    def test_contract_wins_customer_when_system_is_absent(self):
        result = resolve_configuration_precedence(
            contract={"slots": 40}, customer={"slots": 60}
        )
        self.assertEqual(result["effective"]["slots"], 40)
        self.assertEqual(result["provenance"]["slots"], "CONTRACT")

    def test_customer_fills_key_not_defined_above(self):
        result = resolve_configuration_precedence(
            system={"security": {"secure": True}},
            contract={"resources": {"memory_mb": 4096}},
            customer={"hostname": "My server", "resources": {"motd": "hello"}},
        )
        self.assertEqual(result["effective"]["hostname"], "My server")
        self.assertEqual(result["provenance"]["hostname"], "CUSTOMER")
        self.assertEqual(result["effective"]["resources"]["memory_mb"], 4096)
        self.assertEqual(result["effective"]["resources"]["motd"], "hello")
        self.assertEqual(result["provenance"]["resources"]["memory_mb"], "CONTRACT")
        self.assertEqual(result["provenance"]["resources"]["motd"], "CUSTOMER")

    def test_false_zero_null_and_lists_are_atomic_values(self):
        result = resolve_configuration_precedence(
            system={"enabled": False, "limit": 0, "banner": None, "mods": ["system-mod"]},
            contract={"enabled": True, "limit": 10, "banner": "contract", "mods": ["contract-mod"]},
            customer={"enabled": True, "limit": 20, "banner": "customer", "mods": ["customer-mod"]},
        )
        self.assertIs(result["effective"]["enabled"], False)
        self.assertEqual(result["effective"]["limit"], 0)
        self.assertIsNone(result["effective"]["banner"])
        self.assertEqual(result["effective"]["mods"], ["system-mod"])
        for key in ("enabled", "limit", "banner", "mods"):
            self.assertEqual(result["provenance"][key], "SYSTEM")

    def test_layer_input_order_does_not_change_authority(self):
        result = resolve_precedence_document(
            {
                "policy_version": 1,
                "kind": "ConfigurationPrecedence",
                "layers": [
                    {"source": "CUSTOMER", "values": {"value": "customer"}},
                    {"source": "SYSTEM", "values": {"value": "system"}},
                    {"source": "CONTRACT", "values": {"value": "contract"}},
                ],
            }
        )
        self.assertEqual(result["effective"]["value"], "system")
        self.assertEqual(result["precedence"], ["SYSTEM", "CONTRACT", "CUSTOMER"])

    def test_conflicts_are_auditable(self):
        result = resolve_configuration_precedence(
            system={"network": {"port": 2302}},
            contract={"network": {"port": 2402}},
            customer={"network": {"port": 2502}},
        )
        port_conflict = next(item for item in result["conflicts"] if item["path"] == "network.port")
        self.assertEqual(port_conflict["winner"], "SYSTEM")
        self.assertEqual(port_conflict["shadowed"], ["CONTRACT", "CUSTOMER"])

    def test_unknown_or_duplicate_sources_are_rejected(self):
        with self.assertRaises(ConfigurationPrecedenceError):
            resolve_precedence_document(
                {"policy_version": 1, "kind": "ConfigurationPrecedence", "layers": [{"source": "AGENT", "values": {}}]}
            )
        with self.assertRaises(ConfigurationPrecedenceError):
            resolve_precedence_document(
                {
                    "policy_version": 1,
                    "kind": "ConfigurationPrecedence",
                    "layers": [
                        {"source": "SYSTEM", "values": {}},
                        {"source": "SYSTEM", "values": {}},
                    ],
                }
            )

    def test_higher_scalar_owns_container_type(self):
        result = resolve_configuration_precedence(
            system={"runtime": "locked"},
            contract={"runtime": {"variant": "paper"}},
            customer={"runtime": {"variant": "forge"}},
        )
        self.assertEqual(result["effective"]["runtime"], "locked")
        self.assertEqual(result["provenance"]["runtime"], "SYSTEM")


if __name__ == "__main__":
    unittest.main()
