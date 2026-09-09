#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for module_dir in (ROOT, ROOT / "dashboard", ROOT / "database"):
    text = str(module_dir)
    if text not in sys.path:
        sys.path.insert(0, text)

from runtime_instance_projection import canonical_runtime_state, install_runtime_instance_projection


class FakeDashboardRepository:
    def __init__(self, records):
        self.records = records

    def registered_instance_records(self):
        return [dict(item) for item in self.records]


class FakeHealthRepository:
    def __init__(self, values):
        self.values = values

    def initialize(self):
        return None

    def list_for_agent(self, agent_id):
        return [dict(item) for item in self.values.get(agent_id, [])]


class FakeAgentRepository:
    def __init__(self, values):
        self.values = values

    def initialize(self):
        return None

    def snapshot(self, agent_id):
        return {"health_status": self.values.get(agent_id, "unknown")}


def record(status="offline"):
    return {
        "id": "cli-000001-dayz-001",
        "game_id": "dayz",
        "node_id": "horizon-server",
        "agent_id": "agent-horizon-server",
        "customer_id": "cli-000001",
        "name": "HorizonZ",
        "display_name": "HorizonZ",
        "status": status,
    }


class RuntimeProjectionTest(unittest.TestCase):
    def make_legacy(self, root, records, *, legacy_status="offline", create_resource=False):
        if create_resource:
            (root / "runtime" / "resources" / "horizon-server" / "dayz" / "cli-000001-dayz-001").mkdir(parents=True)

        def original_list(database_path):
            return [
                {
                    "server": item["node_id"],
                    "game": item["game_id"],
                    "instance": item["id"],
                    "status": legacy_status,
                    "health": "unknown",
                }
                for item in records
            ]

        def original_summary(server, game, instance):
            base = root / "runtime" / "resources" / server / game / instance
            if not base.exists():
                return {"error": "runtime resource not found", "server": server, "game": game, "instance": instance}
            return {
                "server": server,
                "game": game,
                "instance": instance,
                "server_state": {"status": {"state": legacy_status, "health": "unknown"}},
                "instance_metadata": {"agent_id": "agent-horizon-server"},
                "events": [],
            }

        return SimpleNamespace(
            DSM_ROOT=root,
            DATABASE_FILE=root / "db",
            api_runtime_list=original_list,
            api_runtime_summary=original_summary,
            dashboard_repository=lambda _: FakeDashboardRepository(records),
            backend_from_environment=lambda: object(),
        )

    def install(self, legacy, runtime_values, agent_values):
        return install_runtime_instance_projection(
            legacy,
            health_repository_factory=lambda _: FakeHealthRepository(runtime_values),
            agent_repository_factory=lambda _: FakeAgentRepository(agent_values),
            cache_seconds=0,
        )

    def test_state_normalization_is_explicit(self):
        self.assertEqual(canonical_runtime_state("running"), "online")
        self.assertEqual(canonical_runtime_state("stopped"), "offline")
        self.assertEqual(canonical_runtime_state("failed"), "failed")
        self.assertEqual(canonical_runtime_state("mystery"), "unknown")

    def test_registered_agent_instance_without_legacy_resource_uses_live_running_health(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = [record("offline")]
            legacy = self.make_legacy(root, records, legacy_status="offline")
            self.install(
                legacy,
                {
                    "agent-horizon-server": [
                        {
                            "instance_id": "cli-000001-dayz-001",
                            "desired_state": "running",
                            "observed_state": "running",
                            "health": "healthy",
                            "reported_at": "2026-09-09T10:38:07Z",
                        }
                    ]
                },
                {"agent-horizon-server": "online"},
            )

            listed = legacy.api_runtime_list()[0]
            detail = legacy.api_runtime_summary("horizon-server", "dayz", "cli-000001-dayz-001")

            self.assertEqual(listed["status"], "online")
            self.assertEqual(listed["status_source"], "agent")
            self.assertEqual(listed["observed_state"], "running")
            self.assertNotIn("error", detail)
            self.assertEqual(detail["server_state"]["status"]["state"], "online")
            self.assertEqual(detail["server_state"]["source"], "agent")
            self.assertEqual(detail["instance_metadata"]["agent_id"], "agent-horizon-server")

    def test_live_stopped_overrides_stale_controller_online(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = [record("online")]
            legacy = self.make_legacy(root, records, legacy_status="online", create_resource=True)
            self.install(
                legacy,
                {"agent-horizon-server": [{"instance_id": "cli-000001-dayz-001", "observed_state": "stopped", "health": "offline"}]},
                {"agent-horizon-server": "online"},
            )

            self.assertEqual(legacy.api_runtime_list()[0]["status"], "offline")
            detail = legacy.api_runtime_summary("horizon-server", "dayz", "cli-000001-dayz-001")
            self.assertEqual(detail["server_state"]["status"]["state"], "offline")
            self.assertEqual(detail["server_state"]["source"], "agent")

    def test_offline_agent_does_not_publish_stale_running_as_live(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = [record("online")]
            legacy = self.make_legacy(root, records, legacy_status="online")
            self.install(
                legacy,
                {"agent-horizon-server": [{"instance_id": "cli-000001-dayz-001", "observed_state": "running", "health": "healthy"}]},
                {"agent-horizon-server": "offline"},
            )

            listed = legacy.api_runtime_list()[0]
            detail = legacy.api_runtime_summary("horizon-server", "dayz", "cli-000001-dayz-001")
            self.assertEqual(listed["status"], "unknown")
            self.assertEqual(listed["status_source"], "agent-stale")
            self.assertEqual(detail["server_state"]["status"]["state"], "unknown")
            self.assertEqual(detail["server_state"]["status"]["health"], "stale")

    def test_missing_agent_observation_is_unknown_not_false_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = [record("offline")]
            legacy = self.make_legacy(root, records, legacy_status="offline")
            self.install(legacy, {"agent-horizon-server": []}, {"agent-horizon-server": "online"})

            listed = legacy.api_runtime_list()[0]
            self.assertEqual(listed["status"], "unknown")
            self.assertEqual(listed["status_source"], "agent-unavailable")

    def test_controller_workflow_failure_survives_missing_runtime_telemetry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = [record("failed")]
            legacy = self.make_legacy(root, records, legacy_status="failed")
            self.install(legacy, {"agent-horizon-server": []}, {"agent-horizon-server": "offline"})

            listed = legacy.api_runtime_list()[0]
            self.assertEqual(listed["status"], "failed")
            self.assertEqual(listed["status_source"], "controller")

    def test_unregistered_instance_keeps_not_found_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy = self.make_legacy(root, [])
            self.install(legacy, {}, {})
            detail = legacy.api_runtime_summary("horizon-server", "dayz", "missing")
            self.assertEqual(detail["error"], "runtime resource not found")


if __name__ == "__main__":
    unittest.main()
