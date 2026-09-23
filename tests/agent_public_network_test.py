#!/usr/bin/env python3
"""Contract tests for Agent public DNS/IP, NAT mapping, and Customer connection address."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for module_dir in (DATABASE, DASHBOARD, ROOT):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from agent_public_network import (
    mapped_public_port,
    normalize_public_network,
    player_endpoint,
    public_port_keys,
)
from agent_public_network_schema import ensure_agent_public_network_schema
from customer_instance_connection_http import _external_query_check, _listening_ports, _native_query_failure


class AgentPublicNetworkContractTest(unittest.TestCase):
    def test_public_ipv4_mode_defaults_to_auto_and_accepts_manual(self):
        self.assertEqual(normalize_public_network({"public_ipv4":"201.28.25.63"})["public_ipv4_mode"],"auto")
        self.assertEqual(normalize_public_network({"public_ipv4":"201.28.25.63","public_ipv4_mode":"manual"})["public_ipv4_mode"],"manual")
        with self.assertRaises(ValueError):
            normalize_public_network({"public_ipv4_mode":"invalid"})

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

    def test_ipv6_is_supported_and_bracketed(self):
        endpoint = player_endpoint({"public_ipv6": "2001:db8::10"}, 24566)
        self.assertEqual(endpoint["address"], "[2001:db8::10]:24566")
        self.assertEqual(endpoint["source"], "ipv6")

    def test_missing_public_identity_does_not_invent_private_address(self):
        self.assertIsNone(player_endpoint({}, 24566))

    def test_invalid_hostname_and_ip_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_public_network({"public_hostname": "not a host"})
        with self.assertRaises(ValueError):
            normalize_public_network({"public_ipv4": "192.168.1.999"})
        with self.assertRaises(ValueError):
            normalize_public_network({"public_ipv6": "not-ipv6"})

    def test_invalid_port_is_not_published(self):
        self.assertIsNone(player_endpoint({"public_ipv4": "201.28.25.63"}, 0))
        self.assertIsNone(player_endpoint({"public_ipv4": "201.28.25.63"}, 70000))

    def test_nat_mapping_translates_bind_port_to_public_port(self):
        network = {
            "public_ipv4": "201.28.25.63",
            "nat_scope": "site-sp-01",
            "port_mappings": [
                {"protocol": "udp", "bind_port": 2302, "public_port": 2402},
                {"protocol": "tcp", "bind_port": 2302, "public_port": 2502},
            ],
        }
        endpoint = player_endpoint(network, 2302, protocol="udp")
        self.assertEqual(endpoint["bind_port"], 2302)
        self.assertEqual(endpoint["public_port"], 2402)
        self.assertEqual(endpoint["address"], "201.28.25.63:2402")
        self.assertEqual(mapped_public_port(network, 2302, "tcp"), 2502)

    def test_same_numeric_public_port_can_exist_once_per_protocol(self):
        network = normalize_public_network({
            "public_ipv4": "201.28.25.63",
            "nat_scope": "site-sp-01",
            "port_mappings": [
                {"protocol": "udp", "bind_port": 2302, "public_port": 2402},
                {"protocol": "tcp", "bind_port": 2303, "public_port": 2402},
            ],
        })
        self.assertEqual(public_port_keys(network), {("udp", 2402), ("tcp", 2402)})

    def test_duplicate_public_mapping_same_protocol_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_public_network({
                "public_ipv4": "201.28.25.63",
                "nat_scope": "site-sp-01",
                "port_mappings": [
                    {"protocol": "udp", "bind_port": 2302, "public_port": 2402},
                    {"protocol": "udp", "bind_port": 2303, "public_port": 2402},
                ],
            })

    def test_nat_scope_is_canonicalized(self):
        network = normalize_public_network({"nat_scope": "SITE-SP-01"})
        self.assertEqual(network["nat_scope"], "site-sp-01")

    def test_baseline_extension_supports_all_database_backends(self):
        for backend in ("sqlite", "postgresql", "mysql", "mariadb"):
            sql = ensure_agent_public_network_schema("SELECT 1;", backend)
            self.assertIn("agent_public_network_preconfiguration", sql)
            self.assertIn("public_hostname", sql)
            self.assertIn("public_ipv4", sql)
            self.assertIn("public_ipv6", sql)
            self.assertIn("nat_scope", sql)

    def test_installation_wizards_expose_public_network_fields(self):
        for name in ("add-agent-linux.html", "add-agent-windows.html"):
            text = (ROOT / "dashboard" / "web" / name).read_text(encoding="utf-8")
            self.assertIn('id="agent-public-hostname"', text)
            self.assertIn('id="agent-public-ipv4"', text)

    def test_customer_ui_exposes_copyable_address(self):
        text = (ROOT / "dashboard" / "web" / "customer-instance-connection.js").read_text(encoding="utf-8")
        self.assertIn("ENDEREÇO DO SERVIDOR", text)
        self.assertIn("Copiar endereço", text)
        self.assertIn("QUERY CHECK", text)
        self.assertIn("Verificar publicamente", text)

    def test_customer_port_status_uses_agent_listener_inventory(self):
        rows = _listening_ports(
            {
                "health_status": "online",
                "network": {
                    "udp_complete": True,
                    "tcp_complete": True,
                    "udp_listen": [24000, 24002, 24003],
                    "tcp_listen": [],
                },
            },
            [
                {"name": "game", "protocol": "udp", "port": 24000},
                {"name": "game_aux", "protocol": "udp", "port": 24002},
                {"name": "steam_query", "protocol": "udp", "port": 24003},
                {"name": "battleye", "protocol": "udp", "port": 24004},
            ],
        )
        states = {item["name"]: item["state"] for item in rows}
        self.assertEqual(states["game"], "listening")
        self.assertEqual(states["steam_query"], "listening")
        self.assertEqual(states["battleye"], "reserved")

    def test_native_query_timeout_does_not_mark_confirmed_listener_offline(self):
        result = _native_query_failure(
            {"role": "steam_query", "target": "200.100.203.92:24003"},
            [{"name": "steam_query", "state": "listening"}],
            TimeoutError("timed out"),
        )
        self.assertIsNone(result["online"])
        self.assertTrue(result["listener_online"])
        self.assertFalse(result["public_reachable"])
        self.assertEqual(result["target"], "200.100.203.92:24003")

    def test_native_query_timeout_is_offline_when_listener_is_not_confirmed(self):
        result = _native_query_failure(
            {"role": "steam_query", "target": "200.100.203.92:24003"},
            [{"name": "steam_query", "state": "reserved"}],
            TimeoutError("timed out"),
        )
        self.assertFalse(result["online"])
        self.assertFalse(result["listener_online"])
        self.assertFalse(result["public_reachable"])

    def test_dayz_native_check_queries_actual_reserved_query_port_directly(self):
        check = _external_query_check(
            {
                "gamedig_type": "dayz",
                "checker_type": "valve",
                "protocol": "dayz",
                "strategy": "direct_query_role",
                "game_role": "game",
                "query_role": "steam_query",
                "status": "conditional",
            },
            [
                {"name": "game", "protocol": "udp", "port": 24000},
                {"name": "steam_query", "protocol": "udp", "port": 24003},
            ],
            {"public_ipv4": "200.100.203.92"},
        )
        self.assertIsNotNone(check)
        self.assertEqual(check["port"], 24003)
        self.assertEqual(check["target"], "200.100.203.92:24003")
        self.assertEqual(check["public_port"], 24003)
        self.assertTrue(check["native"])
        self.assertEqual(check["provider"], "capivara-steam-query")
        self.assertEqual(check["test_url"], "/api/customer/instance/connection/test")
        self.assertNotIn("url", check)


if __name__ == "__main__":
    unittest.main()
