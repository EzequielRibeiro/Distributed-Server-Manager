#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"

for path in (ROOT, DASHBOARD, DATABASE):
    sys.path.insert(0, str(path))

import server


class _FakeDashboardRepository:
    def registered_instance_records(self):
        return [
            {
                "id": "cli-000001-dayz-001",
                "node_id": "horizon-server",
                "game_id": "dayz",
                "name": "Servidor DayZ atualizado",
                "status": "failed",
            }
        ]


class DashboardRuntimeListTest(unittest.TestCase):
    def test_registered_instance_is_listed_without_runtime_materialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            self.assertFalse(
                (
                    root
                    / "runtime"
                    / "resources"
                    / "horizon-server"
                    / "dayz"
                    / "cli-000001-dayz-001"
                ).exists()
            )

            with (
                patch.object(server, "DSM_ROOT", root),
                patch.object(
                    server,
                    "dashboard_repository",
                    return_value=_FakeDashboardRepository(),
                ),
            ):
                resources = server.api_runtime_list("ignored.db")

        self.assertEqual(
            resources,
            [
                {
                    "server": "horizon-server",
                    "game": "dayz",
                    "instance": "cli-000001-dayz-001",
                    "name": "Servidor DayZ atualizado",
                    "status": "failed",
                    "health": "unknown",
                }
            ],
        )


    def test_failed_minecraft_is_visible_without_materialized_metadata(self):
        class FailedMinecraftRepository:
            def registered_instance_records(self):
                return [{
                    "id": "cli-000001-minecraft-001",
                    "node_id": "horizon-server",
                    "game_id": "minecraft",
                    "status": "failed",
                }]

            def instance_context(self, instance_id):
                if instance_id != "cli-000001-minecraft-001":
                    return None
                return {
                    "node_id": "horizon-server",
                    "game_id": "minecraft",
                    "customer_id": 1,
                    "controller_id": "controller-horizon-server",
                }

            def permission_profile(self, username, instance_id):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            instances = root / "instances"
            instance = instances / "horizon-server" / "minecraft" / "cli-000001-minecraft-001"
            owner = {"username": "owner", "role": "customer", "scope_id": 1}
            foreign = {"username": "foreign", "role": "customer", "scope_id": 2}
            controller = {"username": "controller", "role": "controller",
                          "scope_id": "controller-horizon-server"}
            with (
                patch.object(server, "DSM_ROOT", root),
                patch.object(server, "INSTANCE_ROOT", instances),
                patch.object(server, "dashboard_repository",
                             return_value=FailedMinecraftRepository()),
            ):
                self.assertFalse((instance / ".dsm" / "instance-metadata.json").exists())
                resources = server.api_runtime_list("ignored.db")
                visible = [item for item in resources if server.can_access_instance(
                    owner, instances / item["server"] / item["game"] / item["instance"])]
                self.assertEqual([item["instance"] for item in visible],
                                 ["cli-000001-minecraft-001"])
                self.assertEqual(visible[0]["status"], "failed")
                self.assertTrue(server.has_instance_permission(
                    owner, instance, "instance.provision.retry", "ignored.db"))
                self.assertFalse(server.can_access_instance(foreign, instance))
                self.assertTrue(server.can_access_instance(controller, instance))
                self.assertFalse(server.can_access_instance(
                    {"role": "controller", "scope_id": "controller-foreign"}, instance))
                self.assertEqual(server.instance_permission_profile(foreign, instance), None)

                # A stale/forged file must not override the registered DB owner.
                metadata_dir = instance / ".dsm"
                metadata_dir.mkdir(parents=True)
                (metadata_dir / "instance-metadata.json").write_text(
                    '{"customer":{"id":2},"controller_id":"controller-foreign"}'
                )
                self.assertTrue(server.can_access_instance(owner, instance))
                self.assertFalse(server.can_access_instance(foreign, instance))
                self.assertFalse(server.can_access_instance(
                    owner, instances / "wrong-node" / "minecraft" /
                    "cli-000001-minecraft-001"))
                self.assertIsNone(server.instance_permission_profile(
                    owner, instances / "horizon-server" / "dayz" /
                    "cli-000001-minecraft-001"))


if __name__ == "__main__":
    unittest.main()
