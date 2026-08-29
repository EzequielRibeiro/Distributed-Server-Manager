#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
AUTH_JS = ROOT / "dashboard" / "web" / "auth.js"
SERVER_PART8 = ROOT / "dashboard" / "server_part8.py"


class LoginRoleRoutingContractTest(unittest.TestCase):
    def test_admin_login_accepts_only_controller_domain_roles(self):
        text = AUTH_JS.read_text(encoding="utf-8")
        self.assertIn('["admin", "controller", "operator"].includes(role)', text)
        self.assertIn('return "/dashboard-v3.html";', text)
        self.assertNotIn('role === "customer"', text)
        self.assertNotIn('return "/customer.html";', text)
        self.assertIn('const destination = destinationForRole(identity?.role);', text)
        self.assertIn('if (!destination)', text)
        self.assertIn('await logout();', text)
        self.assertIn('window.location.replace(destination);', text)

    def test_server_protects_customer_and_controller_areas(self):
        text = SERVER_PART8.read_text(encoding="utf-8")
        self.assertIn('CUSTOMER_PROTECTED_PAGES=', text)
        self.assertIn('CONTROLLER_PROTECTED_PAGES=', text)
        self.assertIn('CONTROLLER_DASHBOARD_FILES=', text)
        self.assertIn('"/dashboard-v3.html"', text)
        self.assertIn('{"customer"}', text)
        self.assertIn('{"admin","controller","operator"}', text.replace(" ", "").replace("\n", ""))
        self.assertIn('Location","/customer-login.html"', text)
        self.assertIn('Location","/login.html"', text)


if __name__ == "__main__":
    unittest.main()
