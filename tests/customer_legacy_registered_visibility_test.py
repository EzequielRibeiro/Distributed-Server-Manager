#!/usr/bin/env python3
"""HTTP regression: CLI-created failed instances inherit verified owner access.

The installed Dashboard entry point imports server_part8, which replaces
server.can_access_instance. Bare server.py tests alone miss this wrapper.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import server
import server_part8


class CustomerLegacyRegisteredVisibilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.instances = Path(self.temp.name) / "instances"
        self.minecraft = (
            self.instances / "horizon-server" / "minecraft"
            / "cli-000001-minecraft-001"
        )
        self.dayz = (
            self.instances / "horizon-server" / "dayz"
            / "cli-000001-dayz-001"
        )
        self.owner = {"username": "aurora", "role": "customer", "scope_id": 1}
        self.other = {"username": "foreign", "role": "customer", "scope_id": 2}
        self.viewer = {"username": "viewer", "role": "customer", "scope_id": 1}

        def registered(path, database_path=server.DATABASE_FILE):
            try:
                node, game, instance = Path(path).relative_to(self.instances).parts
            except (ValueError, FileNotFoundError):
                return False, None
            records = {
                "cli-000001-minecraft-001": {
                    "node_id": "horizon-server", "game_id": "minecraft",
                    "customer_id": 1, "controller_id": "controller-horizon-server",
                },
                "cli-000001-dayz-001": {
                    "node_id": "horizon-server", "game_id": "dayz",
                    "customer_id": 1, "controller_id": "controller-horizon-server",
                },
            }
            record = records.get(instance)
            if record is None:
                return False, None
            if (node, game) != (record["node_id"], record["game_id"]):
                return True, None  # Never fall back to forged file metadata.
            return True, record

        patches = (
            patch.object(server_part8.legacy, "_registered_instance_record", side_effect=registered),
            patch.object(server_part8, "_backend", return_value=object()),
            patch.object(
                server_part8, "account_role_for_user",
                side_effect=lambda user, backend: "owner" if user["username"] == "aurora" else "member",
            ),
            patch.object(
                server_part8, "customer_instance_profile",
                side_effect=lambda user, instance_id, backend: "viewer" if user["username"] == "viewer" else None,
            ),
        )
        for target in patches:
            target.start()
            self.addCleanup(target.stop)

    def test_owner_sees_failed_minecraft_before_materialization(self):
        self.assertFalse((self.minecraft / ".dsm" / "instance-metadata.json").exists())
        self.assertTrue(server_part8.integrated_can_access_instance(self.owner, self.minecraft))
        self.assertEqual(
            server_part8.integrated_instance_permission_profile(self.owner, self.minecraft),
            "manager",
        )
        self.assertTrue(server_part8.integrated_can_access_instance(self.owner, self.minecraft, write=True))

    def test_foreign_account_and_forged_path_fail_closed(self):
        self.assertFalse(server_part8.integrated_can_access_instance(self.other, self.minecraft))
        self.assertFalse(server_part8.integrated_can_access_instance(
            self.owner, self.instances / "other-node" / "minecraft"
            / "cli-000001-minecraft-001",
        ))
        self.assertFalse(server_part8.integrated_can_access_instance(
            self.owner, self.instances / "horizon-server" / "dayz"
            / "cli-000001-minecraft-001",
        ))
        with patch.object(server_part8.legacy, "_registered_instance_record",
                          side_effect=RuntimeError("database is unavailable")):
            self.assertFalse(server_part8.integrated_can_access_instance(self.owner, self.minecraft))

    def test_scoped_viewer_keeps_read_only_profile(self):
        self.assertTrue(server_part8.integrated_can_access_instance(self.viewer, self.minecraft))
        self.assertFalse(server_part8.integrated_can_access_instance(
            self.viewer, self.minecraft, write=True,
        ))

    def test_legacy_http_route_returns_both_owned_instances(self):
        resources = [
            {"server": "horizon-server", "game": "dayz",
             "instance": "cli-000001-dayz-001", "status": "online"},
            {"server": "horizon-server", "game": "minecraft",
             "instance": "cli-000001-minecraft-001", "status": "failed"},
        ]

        class Request:
            path = "/api/runtime/list"
            headers = {"X-Capivara-Auth-Area": "customer"}

            def send_json(self, status, payload):
                self.status = status
                self.payload = payload

            def unauthorized(self):
                raise AssertionError("Authenticated customer rejected")

        with patch.object(server, "INSTANCE_ROOT", self.instances), \
             patch.object(server, "api_runtime_list", return_value=resources), \
             patch.object(server_part8, "integrated_customer_authenticate", return_value=self.owner):
            request = Request()
            server_part8._original_get(request)
            self.assertEqual(request.status, 200)
            self.assertEqual(
                {item["instance"] for item in request.payload},
                {"cli-000001-dayz-001", "cli-000001-minecraft-001"},
            )


if __name__ == "__main__":
    unittest.main()
