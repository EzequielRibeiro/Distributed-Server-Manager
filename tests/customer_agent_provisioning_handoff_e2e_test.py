#!/usr/bin/env python3
"""Prove the real Customer HTTP -> placement -> Agent provisioning handoff.

This closes the seam between the Customer creation regressions and the external
Controller-Agent lifecycle E2E. No game process is installed or started here;
the test ends when the canonical customer creation path has persisted the
instance, reserved its ports and queued the production Agent provisioning
request.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_port_repository import AgentPortRepository
from agent_runtime_repository import AgentRuntimeRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from customer_team_repository import CustomerTeamRepository
from dashboard_repository import DashboardRepository
from customer_instance_creation import install_customer_instance_creation
from instance_creation_http import INSTANCE_CREATE_PATH, dispatch_instance_create_post
from location_repository import LocationRepository
from placement_service import choose_agent_for_instance
from core.placement_requirements import requirements_for_instance
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class _DummyHandler:
    def do_POST(self):
        raise AssertionError("network handler is not used by this integration test")


class CustomerAgentProvisioningHandoffE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="capivara-customer-handoff-")
        self.db_path = Path(self.temp.name) / "capivara.db"
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(self.db_path)))
        self.backend.initialize()

        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="hybrid",
            hostname="customer-handoff-agent",
        )
        self.controller_id = str(identity["controller_id"])
        self.agent_id = str(identity["agent_id"])
        self.node_id = str(identity["node_id"])

        locations = LocationRepository(self.backend)
        locations.upsert_region(
            region_id="br-sudeste",
            name="São Paulo",
            country_code="BR",
            continent_code="SA",
            latitude=-23.55,
            longitude=-46.63,
        )
        locations.upsert_datacenter(
            datacenter_id="dc-customer-handoff",
            region_id="br-sudeste",
            name="Customer Handoff DC",
            provider="e2e",
            city="São Paulo",
            country_code="BR",
            latitude=-23.55,
            longitude=-46.63,
        )
        locations.upsert_agent_location(
            agent_id=self.agent_id,
            datacenter_id="dc-customer-handoff",
            latitude=-23.55,
            longitude=-46.63,
            public_host="203.0.113.10",
        )

        AgentPortRepository(self.backend).set_ranges(
            self.agent_id,
            protocols=("udp",),
            start_port=25000,
            end_port=25199,
        )
        runtime = AgentRuntimeRepository(self.backend)
        runtime.upsert_inventory(
            agent_id=self.agent_id,
            hostname="customer-handoff-agent",
            os_name="linux",
            architecture="x86_64",
            capivara_version="9.9.9-e2e",
            capabilities={
                "platform": {"os": "linux", "architecture": "x86_64"},
                "runtime_profiles": ["dayz", "dayz.stable"],
                "native-linux": True,
                "steamcmd": True,
                "steamcmd_status": {"functional": True},
            },
            cpu={"logical_cores": 8},
            ram_total_bytes=16 * 1024**3,
            storage={"root_free_bytes": 100 * 1024**3},
            network={"tcp_listen": [], "udp_listen": [], "complete": True},
        )
        runtime.heartbeat(self.agent_id)

        with self.backend.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO customers(controller_id,name,status,metadata_json) VALUES (?,?,?,?)",
                (self.controller_id, "Customer Handoff E2E", "active", "{}"),
            )
            self.customer_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT customer_code FROM customers WHERE id=?",
                (self.customer_id,),
            ).fetchone()
            self.customer_code = str(row["customer_code"])
            connection.execute(
                "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit,metadata_json) "
                "VALUES (?,?,?,?,?,?)",
                (
                    "contract-customer-handoff",
                    self.customer_id,
                    "dayz",
                    "active",
                    2,
                    json.dumps(
                        {
                            "resource_profile_id": "standard",
                            "resource_profile_source": "catalog_default",
                        }
                    ),
                ),
            )

        CustomerTeamRepository(self.backend).create_member(
            self.customer_id,
            "customer-handoff",
            "not-a-real-password-hash",
            "member",
        )
        self.legacy = self._legacy_adapter()
        install_customer_instance_creation(self.legacy)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _legacy_adapter(self):
        backend = self.backend
        db_path = self.db_path
        controller_id = self.controller_id

        class Legacy:
            DSM_ROOT = ROOT
            DATABASE_FILE = str(db_path)
            DashboardHandler = _DummyHandler
            INSTANCE_PERMISSIONS = {}

            @staticmethod
            def dashboard_repository(_database_path):
                return DashboardRepository(backend)

            @staticmethod
            def resolve_instance_placement(user, payload, repository):
                placement = payload.get("placement") if isinstance(payload.get("placement"), dict) else {}
                region_id = str(placement.get("region_id") or payload.get("region_id") or "").strip() or None
                requirements = requirements_for_instance(
                    game_id=str(payload.get("game") or "").strip().lower(),
                    runtime_id=str(payload.get("runtime_id") or "").strip(),
                    resources=payload.get("resources") if isinstance(payload.get("resources"), dict) else None,
                    catalog_root=ROOT,
                )
                return choose_agent_for_instance(
                    repository.backend,
                    controller_id=controller_id,
                    preferred_region_id=region_id,
                    requirements=requirements,
                )

            @staticmethod
            def audit(*_args, **_kwargs):
                return None

        return Legacy

    def _user(self):
        return {
            "role": "customer",
            "username": "customer-handoff",
            "customer_id": self.customer_id,
            "customer_code": self.customer_code,
            "scope_id": self.customer_id,
        }

    def _contract(self, user, game):
        if user and int(user.get("scope_id") or 0) == self.customer_id and game == "dayz":
            return "contract-customer-handoff"
        return None

    def test_customer_http_creation_reaches_real_agent_provisioning_queue(self):
        payload = {
            "game": "dayz",
            "runtime_id": "dayz.stable",
            "edition": "default",
            "version": "current",
            "build": "steam-current",
            "contract_id": "contract-customer-handoff",
            "placement": {"region_id": "br-sudeste"},
            "correlation_id": "corr-customer-agent-handoff",
        }

        status, body = dispatch_instance_create_post(
            INSTANCE_CREATE_PATH,
            payload,
            user=self._user(),
            create_instance=lambda user, request: self.legacy.create_customer_instance(
                user,
                request,
                root=ROOT,
                database_path=str(self.db_path),
            ),
            contract_resolver=self._contract,
        )

        self.assertEqual(status, 201, body)
        self.assertTrue(body["created"])
        self.assertEqual(body["correlation_id"], "corr-customer-agent-handoff")
        self.assertEqual(body["placement"]["region_id"], "br-sudeste")
        self.assertNotIn("agent_id", body)
        self.assertNotIn("node_id", body)
        self.assertNotIn("datacenter_id", body)

        instance_id = str(body["instance_id"])
        with self.backend.connect() as connection:
            instance = connection.execute(
                "SELECT agent_id,node_id,game_id,runtime_id,customer_id,status FROM instances WHERE id=?",
                (instance_id,),
            ).fetchone()
            ports = connection.execute(
                "SELECT name,protocol,port FROM instance_ports WHERE instance_id=? ORDER BY port,name",
                (instance_id,),
            ).fetchall()

        self.assertIsNotNone(instance)
        self.assertEqual(str(instance["agent_id"]), self.agent_id)
        self.assertEqual(str(instance["node_id"]), self.node_id)
        self.assertEqual(str(instance["game_id"]), "dayz")
        self.assertEqual(str(instance["runtime_id"]), "dayz.stable")
        self.assertEqual(int(instance["customer_id"]), self.customer_id)
        self.assertEqual(len(ports), 3)
        self.assertEqual({str(row["name"]) for row in ports}, {"game", "game_aux", "steam_query"})
        self.assertTrue(all(str(row["protocol"]) == "udp" for row in ports))

        queue = AgentInstanceProvisioningRepository(self.backend)
        state = queue.latest_for_instance(instance_id)
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], "queued")
        self.assertEqual(state["agent_id"], self.agent_id)
        self.assertEqual(state["environment_id"], "dayz.stable")
        self.assertEqual(state["selector"], "current")

        request = dict(state["request"] or {})
        self.assertEqual(request["kind"], "CapivaraInstanceProvisioningRequest")
        self.assertEqual(request["instance_id"], instance_id)
        self.assertEqual(request["agent_id"], self.agent_id)
        self.assertEqual(request["desired_state"], "stopped")
        self.assertEqual(request["instance"]["game_id"], "dayz")
        self.assertEqual(request["instance"]["runtime_id"], "dayz.stable")
        self.assertEqual(set(request["ports"]), {"game", "game_aux", "steam_query"})
        self.assertEqual(request["content"]["selection"]["provider"], "steam")
        self.assertEqual(request["configuration"]["catalog_runtime_id"], "dayz.stable")
        self.assertEqual(request["configuration"]["catalog_game_id"], "dayz")
        policy = request["configuration"]["catalog_runtime_policy"]
        exposure = {
            str(item.get("name")): str(item.get("exposure"))
            for item in policy.get("network_exposure", [])
        }
        self.assertEqual(exposure, {"game": "public", "game_aux": "public", "steam_query": "public"})

        delivered = queue.command_for_agent(self.agent_id)
        self.assertIsNotNone(delivered)
        self.assertEqual(delivered["provisioning_id"], state["provisioning_id"])
        self.assertEqual(delivered["instance_id"], instance_id)

        # The production queue itself must keep the same active handoff idempotent.
        duplicate = queue.enqueue(
            agent_id=self.agent_id,
            instance_id=instance_id,
            environment_id="dayz.stable",
            selector="current",
            selection=request["content"]["selection"],
            configuration=request["configuration"],
            desired_state="stopped",
            requested_by="customer-handoff",
        )
        self.assertEqual(duplicate["provisioning_id"], state["provisioning_id"])


if __name__ == "__main__":
    unittest.main()
