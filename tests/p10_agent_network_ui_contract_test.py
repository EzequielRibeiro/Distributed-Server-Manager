from pathlib import Path
import unittest


HTML = Path("dashboard/web/agent-details.html").read_text(encoding="utf-8")
JS = Path("dashboard/web/agent-network-panel.js").read_text(encoding="utf-8")
HTTP = Path("dashboard/agent_public_network_http.py").read_text(encoding="utf-8")
API = Path("dashboard/agent_ports_api.py").read_text(encoding="utf-8")


class P10AgentNetworkUiContractTest(unittest.TestCase):
    def test_agent_details_loads_network_panel(self):
        self.assertIn('agent-network-panel.js?v=1', HTML)
        self.assertIn('"/agent-network-panel.js"', HTTP)

    def test_panel_shows_host_network_and_controller_connectivity(self):
        for token in (
            "primary_interface", "primary_ipv4", "primary_ipv6",
            "gateway_ipv4", "gateway_ipv6", "dns_servers", "interfaces",
            "Heartbeat com este Controller", "Inventário de rede",
        ):
            self.assertIn(token, JS)

    def test_panel_shows_tcp_and_udp_port_preflight(self):
        self.assertIn('preflightCard("tcp"', JS)
        self.assertIn('preflightCard("udp"', JS)
        self.assertIn('largest_contiguous_available', JS)
        self.assertIn('result["preflight"]', API)

    def test_same_origin_cookie_auth_is_preserved(self):
        self.assertIn('"X-Capivara-Auth-Area": "controller"', JS)
        self.assertIn('credentials: "same-origin"', JS)
        self.assertNotIn('localStorage.getItem("token"', JS)


if __name__ == "__main__":
    unittest.main()
