from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path("agents/linux/runtime/network_inventory.py")
spec = importlib.util.spec_from_file_location("linux_network_inventory", MODULE_PATH)
network_inventory = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(network_inventory)


class LinuxAgentNetworkInventoryTest(unittest.TestCase):
    def test_collects_primary_interface_addresses_routes_dns_and_ports(self):
        address_rows = [
            {
                "ifname": "lo",
                "operstate": "UNKNOWN",
                "address": "00:00:00:00:00:00",
                "mtu": 65536,
                "flags": ["LOOPBACK", "UP"],
                "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}],
            },
            {
                "ifname": "ens18",
                "operstate": "UP",
                "address": "52:54:00:12:34:56",
                "mtu": 1500,
                "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
                "addr_info": [
                    {"family": "inet", "local": "192.168.15.59", "prefixlen": 24},
                    {"family": "inet6", "local": "fe80::5054:ff:fe12:3456", "prefixlen": 64},
                ],
            },
        ]
        route_rows = [
            {"dst": "default", "gateway": "192.168.15.1", "dev": "ens18", "prefsrc": "192.168.15.59", "metric": 100},
        ]

        def fake_run(args, *, timeout=5):
            del timeout
            if args[:4] == ["ss", "-H", "-l", "-n"]:
                if "-t" in args:
                    return "LISTEN 0 128 0.0.0.0:24000 0.0.0.0:*\n", True
                return "UNCONN 0 0 0.0.0.0:24001 0.0.0.0:*\n", True
            if args == ["ip", "-j", "address", "show"]:
                return json.dumps(address_rows), True
            if args == ["ip", "-j", "route", "show", "default"]:
                return json.dumps(route_rows), True
            raise AssertionError(args)

        with patch.object(network_inventory, "_run", side_effect=fake_run), patch.object(
            network_inventory, "_dns_servers", return_value=(["192.168.15.1", "1.1.1.1"], True)
        ), patch.object(network_inventory.socket, "gethostname", return_value="Node1"), patch.object(
            network_inventory.socket, "getfqdn", return_value="node1.example.internal"
        ):
            result = network_inventory.collect_network_inventory()

        self.assertEqual(result["hostname"], "Node1")
        self.assertEqual(result["fqdn"], "node1.example.internal")
        self.assertEqual(result["primary_interface"], "ens18")
        self.assertEqual(result["primary_ipv4"], "192.168.15.59")
        self.assertEqual(result["default_gateway_ipv4"], "192.168.15.1")
        self.assertEqual(result["dns_servers"], ["192.168.15.1", "1.1.1.1"])
        self.assertEqual(result["tcp_listen"], [24000])
        self.assertEqual(result["udp_listen"], [24001])
        self.assertEqual(result["interfaces"][1]["ipv4"], ["192.168.15.59/24"])
        self.assertTrue(result["complete"])

    def test_partial_collection_is_non_fatal_and_preserves_socket_contract(self):
        with patch.object(network_inventory, "_run", return_value=("", False)), patch.object(
            network_inventory, "_dns_servers", return_value=([], False)
        ):
            result = network_inventory.collect_network_inventory()

        self.assertEqual(result["tcp_listen"], [])
        self.assertEqual(result["udp_listen"], [])
        self.assertIsNone(result["primary_ipv4"])
        self.assertEqual(result["interfaces"], [])
        self.assertFalse(result["complete"])


if __name__ == "__main__":
    unittest.main()
