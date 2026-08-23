#!/usr/bin/env python3

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class DashboardV3NavigationContractTest(unittest.TestCase):
    def test_sidebar_links_resolve_to_existing_html_pages(self):
        sidebar = (WEB / "components" / "sidebar-v3.html").read_text(encoding="utf-8")
        hrefs = re.findall(r'href="([^"#]+)(?:#[^"]*)?"', sidebar)
        self.assertTrue(hrefs)
        for href in hrefs:
            self.assertFalse(href.startswith("index.html"), href)
            self.assertTrue((WEB / href).is_file(), f"sidebar target missing: {href}")

    def test_sidebar_targets_are_registered_by_v3_composition(self):
        sidebar = (WEB / "components" / "sidebar-v3.html").read_text(encoding="utf-8")
        composition = (ROOT / "dashboard" / "server_part14.py").read_text(encoding="utf-8")
        hrefs = set(re.findall(r'href="([^"#]+)(?:#[^"]*)?"', sidebar))
        for href in hrefs:
            self.assertIn(f'"/{href}"', composition, f"sidebar route not registered: {href}")

    def test_infrastructure_links_have_dedicated_destinations(self):
        sidebar = (WEB / "components" / "sidebar-v3.html").read_text(encoding="utf-8")
        self.assertIn('href="infrastructure.html#regions"', sidebar)
        self.assertIn('href="infrastructure.html#datacenters"', sidebar)
        self.assertIn('href="agents.html"', sidebar)
        self.assertIn('href="add-agent.html"', sidebar)
        self.assertIn('href="infrastructure.html#placement"', sidebar)
        infrastructure = (WEB / "infrastructure.html").read_text(encoding="utf-8")
        for section_id in ('id="regions"', 'id="datacenters"', 'id="placement"'):
            self.assertIn(section_id, infrastructure)

    def test_legacy_sidebar_compatibility_path_matches_v3(self):
        current = (WEB / "components" / "sidebar-v3.html").read_text(encoding="utf-8")
        compatibility = (WEB / "components" / "sidebar.html").read_text(encoding="utf-8")
        self.assertEqual(compatibility, current)

    def test_sidebar_keeps_current_rbac_boundaries(self):
        sidebar = (WEB / "components" / "sidebar-v3.html").read_text(encoding="utf-8")
        for marker in ("admin-only", "agent-manager-only", "instance-manager-only"):
            self.assertIn(marker, sidebar)

    def test_primary_admin_pages_use_the_v3_sidebar_contract(self):
        pages = (
            "dashboard-v3.html",
            "infrastructure.html",
            "agents.html",
            "add-agent.html",
            "agent-details.html",
            "servers.html",
            "customers.html",
            "users.html",
            "operations.html",
            "observability.html",
            "system.html",
            "catalog.html",
        )
        for page in pages:
            content = (WEB / page).read_text(encoding="utf-8")
            self.assertIn('id="sidebar-component"', content, page)


if __name__ == "__main__":
    unittest.main()
