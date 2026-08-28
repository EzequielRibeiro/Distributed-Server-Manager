#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
WEB = DASHBOARD / "web"


class BrowserDualPortalAreaHintTest(unittest.TestCase):
    def test_final_composition_routes_legacy_auth_by_explicit_area(self):
        source = (DASHBOARD / "server_part17.py").read_text(encoding="utf-8")
        self.assertIn('X-Capivara-Auth-Area', source)
        self.assertIn('if area=="controller":return _controller_authenticate(headers)', source)
        self.assertIn('if area=="customer":return _customer_authenticate(headers)', source)
        self.assertIn('browser_login_base.integrated_authenticate=_area_aware_authenticate', source)
        self.assertIn('legacy.authenticate=_area_aware_authenticate', source)

    def test_shared_bridge_is_portal_aware(self):
        source = (WEB / "browser-session-bridge.js").read_text(encoding="utf-8")
        self.assertIn('window.location.pathname.startsWith("/customer")', source)
        self.assertIn('const area = customerPage ? "customer" : "controller"', source)
        self.assertIn('headers.set(AREA_HEADER, area)', source)
        self.assertIn('#customer-team-logout,#logout', source)

    def test_customer_navigation_forces_customer_area_and_visible_logout(self):
        source = (WEB / "customer-navigation.js").read_text(encoding="utf-8")
        self.assertIn('headers.set(AREA_HEADER, "customer")', source)
        self.assertIn('logout.hidden = false', source)
        self.assertIn('logout.style.display = "block"', source)
        self.assertIn('logout.textContent = "Sair"', source)
        self.assertIn('/api/customer/auth/logout', source)


if __name__ == "__main__":
    unittest.main()
