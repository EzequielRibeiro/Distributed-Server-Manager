#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"

for module_path in (
    DASHBOARD,
    DATABASE,
):
    sys.path.insert(
        0,
        str(module_path),
    )


from agent_location_http import (
    dispatch_agent_location_post,
)


class AgentLocationHttpTest(
    unittest.TestCase
):
    def test_ignores_unrelated_path(self):
        result = dispatch_agent_location_post(
            "/api/agent/ports/set",
            {},
            user={
                "role": "admin",
            },
            backend=object(),
        )

        self.assertIsNone(
            result
        )

    @patch(
        "agent_location_http."
        "set_agent_location_for_user"
    )
    def test_dispatches_agent_location(
        self,
        set_agent_location_for_user,
    ):
        payload = {
            "agent_id": "agent-demo",
            "datacenter_id": "dc-br-sp",
        }

        expected = {
            "agent_id": "agent-demo",
            "controller_id": "controller-demo",
            "datacenter_id": "dc-br-sp",
            "region_id": "br-southeast",
            "latitude": None,
            "longitude": None,
            "public_host": None,
            "status": "active",
        }

        set_agent_location_for_user.return_value = (
            expected
        )

        status, body = (
            dispatch_agent_location_post(
                "/api/agent/location",
                payload,
                user={
                    "role": "admin",
                },
                backend=object(),
            )
        )

        self.assertEqual(
            status,
            200,
        )
        self.assertEqual(
            body,
            expected,
        )

        set_agent_location_for_user.assert_called_once_with(
            {
                "role": "admin",
            },
            unittest.mock.ANY,
            payload,
        )

    @patch(
        "agent_location_http."
        "set_agent_location_for_user"
    )
    def test_maps_permission_error_to_403(
        self,
        set_agent_location_for_user,
    ):
        set_agent_location_for_user.side_effect = (
            PermissionError(
                "agent is outside user scope"
            )
        )

        status, body = (
            dispatch_agent_location_post(
                "/api/agent/location",
                {
                    "agent_id": "agent-b",
                    "datacenter_id": "dc-b",
                },
                user={
                    "role": "controller",
                    "scope_id": "controller-a",
                },
                backend=object(),
            )
        )

        self.assertEqual(
            status,
            403,
        )
        self.assertEqual(
            body["error"],
            "agent is outside user scope",
        )

    @patch(
        "agent_location_http."
        "set_agent_location_for_user"
    )
    def test_maps_validation_error_to_400(
        self,
        set_agent_location_for_user,
    ):
        set_agent_location_for_user.side_effect = (
            ValueError(
                "datacenter_id is required"
            )
        )

        status, body = (
            dispatch_agent_location_post(
                "/api/agent/location",
                {
                    "agent_id": "agent-demo",
                },
                user={
                    "role": "admin",
                },
                backend=object(),
            )
        )

        self.assertEqual(
            status,
            400,
        )
        self.assertEqual(
            body["error"],
            "datacenter_id is required",
        )

    @patch(
        "agent_location_http."
        "set_agent_location_for_user"
    )
    def test_maps_unexpected_error_to_500(
        self,
        set_agent_location_for_user,
    ):
        set_agent_location_for_user.side_effect = (
            RuntimeError(
                "database unavailable"
            )
        )

        status, body = (
            dispatch_agent_location_post(
                "/api/agent/location",
                {
                    "agent_id": "agent-demo",
                    "datacenter_id": "dc-br-sp",
                },
                user={
                    "role": "admin",
                },
                backend=object(),
            )
        )

        self.assertEqual(
            status,
            500,
        )
        self.assertEqual(
            body,
            {
                "error":
                    "failed to update agent location",
            },
        )


if __name__ == "__main__":
    unittest.main()
