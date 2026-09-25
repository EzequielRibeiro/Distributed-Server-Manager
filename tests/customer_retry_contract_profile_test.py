#!/usr/bin/env python3
"""Provision retries must honor the current active contract resource profile."""
from __future__ import annotations

import json
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import customer_instance_creation as integration


class CustomerRetryContractProfileTest(unittest.TestCase):
    def test_contract_profile_is_selected_from_active_link(self):
        state = {"contract_id": "contract-low", "contract_status": "active",
                 "contract_metadata_json": json.dumps({"resource_profile_id": "low"})}
        self.assertEqual(integration._contracted_retry_profile(state), "low")
        state["contract_metadata_json"] = json.dumps({"resource_profile_id": "advanced"})
        self.assertEqual(integration._contracted_retry_profile(state), "advanced")

    def test_inactive_or_corrupt_contract_fails_closed(self):
        state = {"contract_id": "contract-low", "contract_status": "suspended",
                 "contract_metadata_json": json.dumps({"resource_profile_id": "low"})}
        with self.assertRaises(PermissionError):
            integration._contracted_retry_profile(state)
        state["contract_status"] = "active"
        state["contract_metadata_json"] = "{bad json"
        with self.assertRaises(ValueError):
            integration._contracted_retry_profile(state)

    def test_retry_propagates_low_before_reserving_instance(self):
        events = []

        class Repository:
            backend = object()

            def retry_instance(self, instance_id):
                events.append("read")
                return {"node_id": "horizon-server", "game_id": "minecraft",
                        "contract_id": "contract-low", "contract_status": "active",
                        "contract_metadata_json": json.dumps({"resource_profile_id": "low"})}

            def reserve_retry(self, instance_id, node_id, game_id):
                events.append("reserve")
                return {"runtime_id": "minecraft.java.vanilla", "edition": "java",
                        "game_version": "26.3", "build_id": "26.3",
                        "agent_id": "agent-horizon-server", "status": "failed"}

            def update_instance_status(self, instance_id, status):
                events.append("restore-status")

        class Handler:
            def do_POST(self):
                return None

        legacy = types.SimpleNamespace(
            DashboardHandler=Handler, DSM_ROOT=ROOT,
            DATABASE_FILE=ROOT / "test.db",
            dashboard_repository=lambda _: Repository(), audit=Mock(),
        )
        integration.install_customer_instance_creation(legacy)
        with patch.object(integration, "runtime_definition", return_value={"id": "minecraft.java.vanilla"}), \
             patch.object(integration, "_queue_agent_provisioning",
                          return_value=({"status": "queued"}, {"status": "queued"})) as queue:
            result = legacy.retry_instance_provisioning(
                {"username": "aurora"}, "cli-000001-minecraft-001",
            )
        self.assertTrue(result["retried"])
        self.assertEqual(queue.call_args.kwargs["resource_profile_id"], "low")
        self.assertEqual(events, ["read", "reserve"])

    def test_repository_retry_snapshot_joins_current_contract(self):
        from dashboard_repository import DashboardRepository
        conn = sqlite3.connect(":memory:")
        try:
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE instances(id TEXT,node_id TEXT,game_id TEXT,agent_id TEXT,
                    runtime_id TEXT,edition TEXT,game_version TEXT,build_id TEXT,status TEXT);
                CREATE TABLE instance_contracts(instance_id TEXT,contract_id TEXT);
                CREATE TABLE service_contracts(id TEXT,status TEXT,metadata_json TEXT);
                INSERT INTO instances VALUES('mc-001','horizon','minecraft','agent-horizon',
                    'minecraft.java.vanilla','java','26.3','26.3','failed');
                INSERT INTO instance_contracts VALUES('mc-001','contract-low');
                INSERT INTO service_contracts VALUES('contract-low','active','{"resource_profile_id":"low"}');
            """)
            repo = object.__new__(DashboardRepository)
            repo.dialect = types.SimpleNamespace(placeholder="?")
            repo.session = lambda: conn
            snapshot = repo.retry_instance("mc-001")
            self.assertEqual(integration._contracted_retry_profile(snapshot), "low")
        finally:
            conn.close()


    def test_http_retry_allows_registered_owner_without_instance_access(self):
        class Repository:
            backend = object()

            def instance_context(self, instance_id):
                return {"customer_id": 1, "controller_id": "controller-horizon-server"}

            def permission_profile(self, username, instance_id):
                return None  # CLI-created instances may not have this grant yet.

            def retry_instance(self, instance_id):
                return {"node_id": "horizon-server", "game_id": "minecraft",
                        "contract_id": "contract-low", "contract_status": "active",
                        "contract_metadata_json": '{"resource_profile_id":"low"}'}

            def reserve_retry(self, instance_id, node_id, game_id):
                return {"runtime_id": "minecraft.java.vanilla", "edition": "java",
                        "game_version": "26.3", "build_id": "26.3",
                        "agent_id": "agent-horizon-server", "status": "failed"}

        class Handler:
            path = "/api/instance/provision/retry"
            headers = {}

            def read_json_body(self):
                return {"instance_id": "cli-000001-minecraft-001"}

            def send_json(self, status, data):
                self.response = (status, data)

            def forbidden(self):
                self.response = (403, None)

            def unauthorized(self):
                self.response = (401, None)

            def do_POST(self):
                raise AssertionError("retry route was not installed")

        user = [{"username": "owner", "role": "customer", "scope_id": 1}]
        legacy = types.SimpleNamespace(
            DashboardHandler=Handler, DSM_ROOT=ROOT, DATABASE_FILE=ROOT / "test.db",
            dashboard_repository=lambda _: Repository(),
            authenticate=lambda headers: user[0],
            can_write=lambda actor: True,
            INSTANCE_PERMISSIONS={"manager": {"instance.provision.retry"}},
            audit=Mock(),
        )
        integration.install_customer_instance_creation(legacy)
        with patch.object(integration, "runtime_definition", return_value={"id": "minecraft.java.vanilla"}), \
             patch.object(integration, "_queue_agent_provisioning",
                          return_value=({"status": "queued"}, {"status": "queued"})) as queue:
            owner_handler = legacy.DashboardHandler()
            owner_handler.do_POST()
            self.assertEqual(owner_handler.response[0], 200)
            self.assertEqual(queue.call_args.kwargs["resource_profile_id"], "low")
            user[0] = {"username": "foreign", "role": "customer", "scope_id": 2}
            foreign_handler = legacy.DashboardHandler()
            foreign_handler.do_POST()
            self.assertEqual(foreign_handler.response[0], 403)
            self.assertEqual(queue.call_count, 1)

if __name__ == "__main__":
    unittest.main()
