#!/usr/bin/env python3

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from instance_creation_http import dispatch_instance_create_post
from placement_errors import PlacementUnavailable


class InstanceCreationHttpTest(unittest.TestCase):
    def setUp(self):
        self.user = {
            "username": "customer-one",
            "role": "customer",
            "scope_id": "customer-001",
        }
        self.payload = {
            "game": "dayz",
            "placement": {"region_id": "br-se"},
        }

    def test_placement_unavailable_returns_controlled_conflict(self):
        logs = []

        def create_instance(user, payload):
            raise PlacementUnavailable(
                reason="agent_pending",
                agents_evaluated=2,
                requested_region_id="br-se",
            )

        result = dispatch_instance_create_post(
            "/api/instance/create",
            self.payload,
            user=self.user,
            create_instance=create_instance,
            contract_resolver=lambda user, game: "contract-dayz-001",
            log=logs.append,
        )

        self.assertEqual(
            result,
            (
                409,
                {
                    "error": "placement_unavailable",
                    "message": "Nenhum ambiente está disponível para criar este servidor.",
                },
            ),
        )
        self.assertNotIn("agent_pending", json.dumps(result[1]))
        self.assertEqual(len(logs), 1)
        record = json.loads(logs[0])
        self.assertEqual(record["customer"], "customer-001")
        self.assertEqual(record["contract"], "contract-dayz-001")
        self.assertEqual(record["game"], "dayz")
        self.assertEqual(record["region"], "br-se")
        self.assertEqual(record["reason"], "agent_pending")
        self.assertEqual(record["agents_evaluated"], 2)

    def test_unexpected_runtime_error_never_escapes_http_boundary(self):
        def create_instance(user, payload):
            raise RuntimeError("internal placement detail")

        status, body = dispatch_instance_create_post(
            "/api/instance/create",
            self.payload,
            user=self.user,
            create_instance=create_instance,
        )

        self.assertEqual(status, 500)
        self.assertEqual(body["error"], "instance_creation_failed")
        self.assertNotIn("internal placement detail", json.dumps(body))

    def test_success_returns_created(self):
        status, body = dispatch_instance_create_post(
            "/api/instance/create",
            self.payload,
            user=self.user,
            create_instance=lambda user, payload: {"instance_id": "srv-001"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["instance_id"], "srv-001")

    def test_permission_error_is_controlled(self):
        def create_instance(user, payload):
            raise PermissionError("internal permission detail")

        status, body = dispatch_instance_create_post(
            "/api/instance/create",
            self.payload,
            user=self.user,
            create_instance=create_instance,
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden")

    def test_other_path_is_not_handled(self):
        result = dispatch_instance_create_post(
            "/api/other",
            self.payload,
            user=self.user,
            create_instance=lambda user, payload: {},
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
