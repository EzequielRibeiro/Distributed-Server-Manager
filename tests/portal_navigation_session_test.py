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

    def test_customer_demo_uses_customer_cookie_even_when_controller_cookie_also_exists(self):
        handler = _Handler("/contract-demo.html?game=minecraft")
        with patch.object(guard, "session_user_from_headers") as resolve:
            resolve.side_effect = lambda _headers, area: {"role": "customer"} if area == "customer" else {"role": "admin"}
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("file", "contract-demo.html"), handler.events)
        resolve.assert_called_once_with(handler.headers, area="customer")

    def test_controller_page_without_controller_session_redirects_to_controller_login(self):
        handler = _Handler("/activity-log.html")
        with patch.object(guard, "session_user_from_headers", return_value=None):
            _Legacy.DashboardHandler.do_GET(handler)
        self.assertIn(("status", 302), handler.events)
        self.assertIn(("header", "Location", "/login.html"), handler.events)

    def test_customer_demo_without_customer_session_redirects_to_customer_login(self):
        handler = _Handler("/contract-demo.html?game=dayz")
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
