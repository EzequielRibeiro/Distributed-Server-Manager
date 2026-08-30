from pathlib import Path
import importlib.util
import unittest
from unittest import mock


MODULE_PATH = Path("agents/windows/runtime/network_inventory.py")
spec = importlib.util.spec_from_file_location("windows_network_inventory", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class WindowsAgentNetworkInventoryTest(unittest.TestCase):
    def identity_payload(self):
        return {
            "adapters": [{
                "name": "Ethernet",
                "interface_index": 12,
                "status": "Up",
                "mac": "AA-BB-CC-DD-EE-FF",
                "mtu": 1500,
                "ipv4": ["10.10.0.12"],
                "ipv6": ["2001:db8::12", "fe80::12"],
                "gateway4": ["10.10.0.1"],
                "gateway6": [],
                "dns": ["10.10.0.53", "1.1.1.1"],
            }],
            "default4": {"interface_index": 12, "gateway": "10.10.0.1"},
            "default6": None,
        }

    def test_collects_identity_and_ports(self):
        tcp = "  TCP    0.0.0.0:8080    0.0.0.0:0    LISTENING    123\n"
        udp = "  UDP    0.0.0.0:24000   *:*                     456\n"

        def fake_run(command, timeout=10):
            return (tcp if command[-1] == "tcp" else udp), True

        with mock.patch.object(module, "_run", side_effect=fake_run), \
             mock.patch.object(module, "_powershell_inventory", return_value=(self.identity_payload(), True)), \
             mock.patch.object(module.socket, "gethostname", return_value="win-node"), \
             mock.patch.object(module.socket, "getfqdn", return_value="win-node.example"):
            result = module.collect_network_inventory()

        self.assertEqual(result["primary_interface"], "Ethernet")
        self.assertEqual(result["primary_ipv4"], "10.10.0.12")
        self.assertEqual(result["primary_ipv6"], "2001:db8::12")
        self.assertEqual(result["gateway_ipv4"], "10.10.0.1")
        self.assertEqual(result["dns_servers"], ["10.10.0.53", "1.1.1.1"])
        self.assertEqual(result["tcp_listen"], [8080])
        self.assertEqual(result["udp_listen"], [24000])
        self.assertTrue(result["complete"])

    def test_powershell_failure_keeps_socket_inventory(self):
        with mock.patch.object(module, "_run", return_value=("", True)), \
             mock.patch.object(module, "_powershell_inventory", return_value=({}, False)):
            result = module.collect_network_inventory()
        self.assertFalse(result["identity_complete"])
        self.assertTrue(result["tcp_complete"])
        self.assertFalse(result["complete"])

    def test_legacy_netstat_mock_consumes_only_two_subprocess_run_calls(self):
        completed_tcp = mock.Mock(stdout="  TCP    0.0.0.0:8080    0.0.0.0:0    LISTENING    123\n")
        completed_udp = mock.Mock(stdout="  UDP    0.0.0.0:24000   *:*                     456\n")
        with mock.patch.object(module.subprocess, "run", side_effect=[completed_tcp, completed_udp]) as run, \
             mock.patch.object(module, "_powershell_inventory", return_value=({}, False)):
            result = module.collect_network_inventory()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result["tcp_listen"], [8080])
        self.assertEqual(result["udp_listen"], [24000])


if __name__ == "__main__":
    unittest.main()
