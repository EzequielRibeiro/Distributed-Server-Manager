#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"
for path in (DASHBOARD, DATABASE):
    sys.path.insert(0, str(path))

from infrastructure_http import dispatch_infrastructure_get


class InfrastructureHttpTest(unittest.TestCase):
    def test_ignores_unrelated_path(self):
        result = dispatch_infrastructure_get(
            "/api/agents",
            "",
            user={"role": "admin"},
            backend=object(),
        )
        self.assertIsNone(result)

    @patch("infrastructure_http.infrastructure_for_user")
    def test_dispatches_topology_request(self, infrastructure_for_user):
        infrastructure_for_user.return_value = {"controllers": []}
        status, body = dispatch_infrastructure_get(
            "/api/infrastructure",
            "controller_id=controller-a&active_only=true",
            user={"role": "admin"},
            backend=object(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, {"controllers": []})
        infrastructure_for_user.assert_called_once_with(
            {"role": "admin"},
            unittest.mock.ANY,
            controller_id="controller-a",
            active_only=True,
        )

    @patch("infrastructure_http.infrastructure_for_user")
    def test_maps_permission_error_to_403(self, infrastructure_for_user):
        infrastructure_for_user.side_effect = PermissionError("outside scope")
        status, body = dispatch_infrastructure_get(
            "/api/infrastructure",
            "",
            user={"role": "controller", "scope_id": "controller-a"},
            backend=object(),
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "outside scope")

    @patch("infrastructure_http.infrastructure_for_user")
    def test_maps_missing_controller_to_404(self, infrastructure_for_user):
        infrastructure_for_user.side_effect = ValueError("controller not found")
        status, body = dispatch_infrastructure_get(
            "/api/infrastructure",
            "controller_id=missing",
            user={"role": "admin"},
            backend=object(),
        )
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "controller not found")


if __name__ == "__main__":
    unittest.main()
