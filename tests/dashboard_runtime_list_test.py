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
                    "status": "failed",
                    "health": "unknown",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
