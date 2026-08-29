#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

import portal_navigation_session_http as guard


class _Handler:
    def __init__(self, path):
        self.path = path
        self.headers = {}
        self.events = []
    def send_response(self, code): self.events.append(("status", code))
    def send_header(self, name, value): self.events.append(("header", name, value))
    def end_headers(self): self.events.append(("end",))
    def send_json(self, code, payload): self.events.append(("json", code, payload))
    def send_file(self, target): self.events.append(("file", str(target)))


class _Legacy:
    STATIC_FILES = {
        "/activity-log.html": Path("activity-log.html"),
        "/contract-demo.html": Path("contract-demo.html"),
        "/customer.html": Path("customer.html"),
        "/customer.js": Path("customer-shell.js"),
        "/customer-core.js": Path("customer.js"),
        "/customer-navigation.js": Path("customer-navigation.js"),
        "/customer.css": Path("customer.css"),
        "/components/sidebar-v3.html": Path("components/sidebar-v3.html"),
        "/catalog-page.css": Path("catalog-page.css"),
    }
    class DashboardHandler:
        pass


class PortalNavigationSessionTest(unittest.TestCase):
    def setUp(self):
        def previous(handler):
            handler.events.append(("previous",))
        _Legacy.DashboardHandler.do_GET = previous
        guard.install_portal_navigation_session_guard(_Legacy)

    def test_controller_page_uses_controller_cookie_even_when_customer_cookie_also_exists(self):
        handler = _Handler("/activity-log.html")
        with patch.object(guard, "session_user_from_headers") as resolve:
            resolve.side_effect = lambda _headers, area: {"role": "admin"} if area == "controller" else {"role": "customer"}
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("file", "activity-log.html"), handler.events)
        resolve.assert_called_once_with(handler.headers, area="controller")

    def test_controller_asset_uses_controller_cookie_even_when_customer_cookie_also_exists(self):
        handler = _Handler("/components/sidebar-v3.html")
        with patch.object(guard, "session_user_from_headers") as resolve:
            resolve.side_effect = lambda _headers, area: {"role": "admin"} if area == "controller" else {"role": "customer"}
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("file", "components/sidebar-v3.html"), handler.events)
        resolve.assert_called_once_with(handler.headers, area="controller")

    def test_controller_stylesheet_uses_controller_cookie_even_when_customer_cookie_also_exists(self):
        handler = _Handler("/catalog-page.css?v=3")
        with patch.object(guard, "session_user_from_headers", return_value={"role": "controller"}) as resolve:
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("file", "catalog-page.css"), handler.events)
        resolve.assert_called_once_with(handler.headers, area="controller")

    def test_controller_asset_without_controller_session_returns_unauthorized(self):
        handler = _Handler("/components/sidebar-v3.html")
        with patch.object(guard, "session_user_from_headers", return_value=None):
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("json", 401, {"error": "authentication_required"}), handler.events)
        self.assertNotIn(("header", "Location", "/login.html"), handler.events)

    def test_customer_page_uses_customer_cookie_even_when_controller_cookie_also_exists(self):
        handler = _Handler("/customer.html")
        with patch.object(guard, "session_user_from_headers") as resolve:
            resolve.side_effect = lambda _headers, area: {"role": "customer"} if area == "customer" else {"role": "admin"}
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("file", "customer.html"), handler.events)
        resolve.assert_called_once_with(handler.headers, area="customer")

    def test_customer_demo_uses_customer_cookie_even_when_controller_cookie_also_exists(self):
        handler = _Handler("/contract-demo.html?game=minecraft")
        with patch.object(guard, "session_user_from_headers") as resolve:
            resolve.side_effect = lambda _headers, area: {"role": "customer"} if area == "customer" else {"role": "admin"}
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("file", "contract-demo.html"), handler.events)
        resolve.assert_called_once_with(handler.headers, area="customer")

    def test_customer_bootstrap_asset_uses_customer_cookie_with_dual_sessions(self):
        handler = _Handler("/customer.js?v=4")
        with patch.object(guard, "session_user_from_headers") as resolve:
            resolve.side_effect = lambda _headers, area: {"role": "customer"} if area == "customer" else {"role": "admin"}
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("file", "customer-shell.js"), handler.events)
        resolve.assert_called_once_with(handler.headers, area="customer")

    def test_customer_dynamic_core_asset_uses_customer_cookie_with_dual_sessions(self):
        handler = _Handler("/customer-core.js?v=3")
        with patch.object(guard, "session_user_from_headers") as resolve:
            resolve.side_effect = lambda _headers, area: {"role": "customer"} if area == "customer" else {"role": "admin"}
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("file", "customer.js"), handler.events)
        resolve.assert_called_once_with(handler.headers, area="customer")

    def test_customer_asset_without_customer_session_returns_unauthorized(self):
        handler = _Handler("/customer-navigation.js?v=2")
        with patch.object(guard, "session_user_from_headers", return_value=None):
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("json", 401, {"error": "authentication_required"}), handler.events)
        self.assertNotIn(("header", "Location", "/customer-login.html"), handler.events)

    def test_controller_page_without_controller_session_redirects_to_controller_login(self):
        handler = _Handler("/activity-log.html")
        with patch.object(guard, "session_user_from_headers", return_value=None):
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("status", 302), handler.events)
        self.assertIn(("header", "Location", "/login.html"), handler.events)

    def test_customer_page_without_customer_session_redirects_to_customer_login(self):
        handler = _Handler("/customer.html")
        with patch.object(guard, "session_user_from_headers", return_value=None):
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("status", 302), handler.events)
        self.assertIn(("header", "Location", "/customer-login.html"), handler.events)

    def test_server_part17_installs_guard_after_browser_session_boundary(self):
        source = (DASHBOARD / "server_part17.py").read_text(encoding="utf-8")
        self.assertIn("install_portal_navigation_session_guard", source)
        self.assertLess(source.index("install_browser_session_http(legacy"), source.index("install_portal_navigation_session_guard(legacy)"))


if __name__ == "__main__":
    unittest.main()
