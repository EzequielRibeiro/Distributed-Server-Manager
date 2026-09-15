#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class InfrastructureLocationAdminUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.regions = (WEB / "regions.html").read_text(encoding="utf-8")
        cls.datacenters = (WEB / "datacenters.html").read_text(encoding="utf-8")
        cls.admin_js = (WEB / "infrastructure-location-admin.js").read_text(encoding="utf-8")
        cls.infrastructure_js = (WEB / "infrastructure-v3.js").read_text(encoding="utf-8")
        cls.composition = (ROOT / "dashboard" / "server_part14.py").read_text(encoding="utf-8")
        cls.latest = (ROOT / "dashboard" / "server_part17.py").read_text(encoding="utf-8")

    def test_region_editor_is_admin_only(self):
        for marker in (
            'id="infra-region-new"',
            'id="infra-region-form"',
            'id="infra-region-country-code"',
            'id="infra-region-status"',
            "data-location-admin",
        ):
            self.assertIn(marker, self.regions)
        self.assertIn("/infrastructure-location-admin.js?v=1", self.regions)

    def test_datacenter_editor_has_public_geography_fields(self):
        for marker in (
            'id="infra-datacenter-form"',
            'id="infra-datacenter-country-code"',
            'id="infra-datacenter-country-name"',
            'id="infra-datacenter-state-code"',
            'id="infra-datacenter-state-name"',
            'id="infra-datacenter-city"',
            'id="infra-datacenter-status"',
        ):
            self.assertIn(marker, self.datacenters)

    def test_admin_client_posts_canonical_topology_routes(self):
        for marker in (
            'const API = "/api/infrastructure"',
            'request("/regions"',
            'request("/datacenters"',
            "country_name:",
            "state_code:",
            "state_name:",
            'role !== "admin"',
        ):
            self.assertIn(marker, self.admin_js)

    def test_disabled_topology_is_visible_only_on_admin_pages(self):
        self.assertIn('["regions.html","datacenters.html"].includes(page)', self.infrastructure_js)
        self.assertIn('active_only=${activeOnly?"true":"false"}', self.infrastructure_js)
        self.assertIn('dc.status!=="disabled"', self.infrastructure_js)

    def test_admin_assets_and_routes_are_composed(self):
        self.assertIn('"/infrastructure-location-admin.js"', self.composition)
        self.assertIn("install_location_administration", self.latest)


if __name__ == "__main__":
    unittest.main()
