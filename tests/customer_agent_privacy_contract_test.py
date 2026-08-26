#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import customer_instance_creation as creation


class _Handler:
    def do_POST(self):
        return None


class _Repository:
    def __init__(self):
        self.backend = object()

    def create_customer_instance(self, **kwargs):
        # Agent and node assignment are internal Controller data. Deliberately
        # include both here so this test fails if the public response starts
        # projecting either identifier.
        return {
            "instance_id": "cli000001-dayz-001",
            "name": "Servidor DayZ",
            "contract_id": "contract-1",
            "agent_id": "agent-private-123",
            "node_id": "node-private-456",
        }

    def delete_instance(self, instance_id):
        raise AssertionError(f"unexpected rollback for {instance_id}")


class CustomerAgentPrivacyContractTest(unittest.TestCase):
    def test_customer_creation_response_never_exposes_selected_agent_or_node(self):
        repository = _Repository()
        legacy = SimpleNamespace(
            DashboardHandler=_Handler,
            DSM_ROOT=ROOT,
            DATABASE_FILE=ROOT / "data" / "unused-test.db",
            dashboard_repository=lambda _path: repository,
            resolve_instance_placement=lambda _user, _payload, _repository: {
                "agent_id": "agent-private-123",
                "node_id": "node-private-456",
                "region_id": "br-sudeste",
                "datacenter_id": "dc-limeira",
                "score": 98,
                "reason": "capacity",
            },
            INSTANCE_PERMISSIONS={},
            authenticate=lambda _headers: None,
            can_write=lambda _user: False,
            audit=lambda *args, **kwargs: None,
        )

        creation.install_customer_instance_creation(legacy)
        payload = {
            "game": "dayz",
            "runtime_id": "dayz.stable",
            "edition": "stable",
            "version": "1.0",
            "build": "current",
            "contract_id": "contract-1",
        }
        user = {"role": "customer", "scope_id": "cli000001", "username": "cliente"}

        with (
            patch.object(creation, "runtime_definition", return_value={"id": "dayz.stable", "variant": "stable", "network": {}}),
            patch.object(creation, "resolve_customer_reference", return_value="cli000001"),
            patch.object(creation, "InstanceBackupCloneRepository", return_value=MagicMock()),
            patch.object(creation, "occupied_ports_provider_for_backend", return_value=lambda: set()),
            patch.object(
                creation,
                "_queue_agent_provisioning",
                return_value=(
                    {"provisioning_id": "provision-1"},
                    {
                        "status": "queued",
                        "stage": "queued",
                        "progress": 5,
                        "message": "Instalação aguardando o Agent…",
                        "distributed": True,
                        "provisioning_id": "provision-1",
                    },
                ),
            ),
        ):
            result = legacy.create_customer_instance(user, payload)

        self.assertTrue(result["created"])
        self.assertEqual(result["placement"]["region_id"], "br-sudeste")
        self.assertEqual(result["placement"]["datacenter_id"], "dc-limeira")
        self.assertNotIn("agent_id", result)
        self.assertNotIn("node_id", result)
        self.assertNotIn("agent_id", result["placement"])
        self.assertNotIn("node_id", result["placement"])

        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("agent-private-123", serialized)
        self.assertNotIn("node-private-456", serialized)


if __name__ == "__main__":
    unittest.main()
