#!/usr/bin/env python3
"""Contract tests for Agent public DNS/IP and Customer connection address."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from agent_public_network import normalize_public_network, player_endpoint
from agent_public_network_schema import ensure_agent_public_network_schema


class AgentPublicNetworkContractTest(unittest.TestCase):
    def test_hostname_has_priority_over_ipv4(self):
        endpoint = player_endpoint(
            {"public_hostname": "BR-SP01.Capivara.Games.", "public_ipv4": "201.28.25.63"},
            24566,
        )
        self.assertEqual(endpoint["address"], "br-sp01.capivara.games:24566")
        self.assertEqual(endpoint["source"], "dns")

    def test_ipv4_is_fallback_when_dns_is_absent(self):
        endpoint = player_endpoint({"public_hostname": None, "public_ipv4": "201.28.25.63"}, 24566)
        self.assertEqual(endpoint["address"], "201.28.25.63:24566")
        self.assertEqual(endpoint["source"], "ipv4")

    def test_missing_public_identity_does_not_invent_private_address(self):
        self.assertIsNone(player_endpoint({}, 24566))

    def test_invalid_hostname_and_ipv4_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_public_network({"public_hostname": "not a host"})
        with self.assertRaises(ValueError):
            normalize_public_network({"public_ipv4": "192.168.1.999"})

    def test_invalid_port_is_not_published(self):
        self.assertIsNone(player_endpoint({"public_ipv4": "201.28.25.63"}, 0))
        self.assertIsNone(player_endpoint({"public_ipv4": "201.28.25.63"}, 70000))

    def test_baseline_extension_supports_all_database_backends(self):
        for backend in ("sqlite", "postgresql", "mysql", "mariadb"):
            sql = ensure_agent_public_network_schema("SELECT 1;", backend)
            self.assertIn("agent_public_network_preconfiguration", sql)
            self.assertIn("public_hostname", sql)
            self.assertIn("public_ipv4", sql)

    def test_installation_wizards_expose_public_network_fields(self):
        for name in ("add-agent-linux.html", "add-agent-windows.html"):
            text = (ROOT / "dashboard" / "web" / name).read_text(encoding="utf-8")
            self.assertIn('id="agent-public-hostname"', text)
            self.assertIn('id="agent-public-ipv4"', text)

    def test_customer_ui_exposes_copyable_address(self):
        text = (ROOT / "dashboard" / "web" / "customer-instance-connection.js").read_text(encoding="utf-8")
        self.assertIn("ENDEREÇO DO SERVIDOR", text)
        self.assertIn("Copiar endereço", text)


if __name__ == "__main__":
    unittest.main()
