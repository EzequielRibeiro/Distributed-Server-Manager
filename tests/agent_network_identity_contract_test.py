from pathlib import Path
import unittest


PORTS_API = Path("dashboard/agent_ports_api.py")
DETAILS_JS = Path("dashboard/web/agent-details.js")


class AgentNetworkIdentityContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = PORTS_API.read_text(encoding="utf-8")
        cls.ui = DETAILS_JS.read_text(encoding="utf-8")

    def test_runtime_network_identity_falls_back_to_primary_address(self):
        self.assertIn('network.get("primary_ipv4")', self.api)
        self.assertIn('network.get("primary_ipv6")', self.api)
        self.assertIn('"network": network', self.api)

    def test_location_join_supplies_existing_agent_detail_fields(self):
        self.assertIn("FROM agent_locations al", self.api)
        self.assertIn("JOIN datacenters d", self.api)
        self.assertIn("JOIN regions r", self.api)
        for field in ("datacenter_name", "region_name", "public_host", "region_id"):
            self.assertIn(field, self.api)

    def test_agent_details_keeps_network_and_placement_bindings(self):
        self.assertIn('text("detail-address"', self.ui)
        self.assertIn('text("detail-datacenter"', self.ui)
        self.assertIn('text("detail-region"', self.ui)
        self.assertIn('text("detail-public-host"', self.ui)
        self.assertIn('text("detail-node"', self.ui)


if __name__ == "__main__":
    unittest.main()
