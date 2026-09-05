#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "dashboard" / "static_asset_policy.py"
GUARD_PATH = ROOT / "dashboard" / "portal_navigation_session_http.py"


def load_policy():
    spec = importlib.util.spec_from_file_location("static_asset_policy_under_test", POLICY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class StaticAssetAuthPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy()
        cls.guard_source = GUARD_PATH.read_text(encoding="utf-8")

    def test_policy_groups_do_not_overlap(self):
        controller = self.policy.CONTROLLER_STATIC_PATHS
        customer = self.policy.CUSTOMER_STATIC_PATHS
        shared = self.policy.SHARED_PUBLIC_STATIC_PATHS
        self.assertFalse(controller & customer)
        self.assertFalse(controller & shared)
        self.assertFalse(customer & shared)

    def test_agent_danger_zone_assets_are_controller_scoped(self):
        controller = self.policy.CONTROLLER_STATIC_PATHS
        for path in {
            "/agent-uninstall-admin.js",
            "/agent-identity-rebind.js",
            "/agent-network-panel.js",
            "/storage-pool-source-cleanup.js",
        }:
            self.assertIn(path, controller)

    def test_customer_workspace_assets_are_customer_scoped(self):
        customer = self.policy.CUSTOMER_STATIC_PATHS
        for path in {
            "/customer-instance.html",
            "/customer-instance-v2.css",
            "/customer-instance-v2.js",
            "/customer-instance-core.js",
            "/customer-navigation.js",
            "/create-server-wizard.js",
        }:
            self.assertIn(path, customer)

    def test_shared_assets_are_area_neutral(self):
        shared = self.policy.SHARED_PUBLIC_STATIC_PATHS
        self.assertIn("/browser-auth-client.js", shared)
        self.assertIn("/telemetry-widgets.js", shared)
        self.assertIn("/telemetry-widgets.css", shared)

    def test_guard_uses_canonical_policy(self):
        self.assertIn("from static_asset_policy import", self.guard_source)
        self.assertIn("if path in CONTROLLER_STATIC_PATHS", self.guard_source)
        self.assertIn("if path in CUSTOMER_STATIC_PATHS", self.guard_source)
        self.assertIn("if path in SHARED_PUBLIC_STATIC_PATHS", self.guard_source)

    def test_guard_authenticates_each_portal_explicitly(self):
        self.assertIn('session_user_from_headers(handler.headers, area="controller")', self.guard_source)
        self.assertIn('session_user_from_headers(handler.headers, area="customer")', self.guard_source)
        self.assertNotIn("integrated_authenticate(handler.headers)", self.guard_source)


if __name__ == "__main__":
    unittest.main()
