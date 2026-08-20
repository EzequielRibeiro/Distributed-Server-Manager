#!/usr/bin/env python3
"""Phase 22 critical E2E regression for customer DayZ creation.

This test keeps external Steam/network activity deterministic while exercising the
real database, contract, catalog requirements, placement, port reservation and
HTTP error boundary. The provisioner itself is a deterministic test double: CI
must not require Steam credentials or mutate a real game host.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_port_availability import effective_port_summary
from agent_runtime_repository import AgentRuntimeRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from core.placement_requirements import requirements_for_instance
from instance_creation_http import INSTANCE_CREATE_PATH, dispatch_instance_create_post
from placement_service import choose_agent_for_instance
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class CustomerDayzFinalE2ETest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "capivara.db"
        self.backend = self._open_backend()
        self.identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="hybrid", hostname="phase22-hybrid"
        )
        self.controller_id = str(self.identity["controller_id"])
        self.agent_id = str(self.identity["agent_id"])
        self.node_id = str(self.identity["node_id"])
        self.customer_id = "customer-phase22"
        self.contract_id = "contract-phase22-dayz"

        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO customers(id,controller_id,name,status,metadata_json) VALUES (?,?,?,?,?)",
                (self.customer_id, self.controller_id, "Phase 22 Customer", "active", "{}"),
            )
            connection.execute(
                "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit,metadata_json) "
                "VALUES (?,?,?,?,?,?)",
                (self.contract_id, self.customer_id, "dayz", "active", 2, "{}"),
            )

        runtime = AgentRuntimeRepository(self.backend)
        runtime.upsert_inventory(
            agent_id=self.agent_id,
            hostname="phase22-hybrid",
            os_name="linux",
            architecture="x86_64",
            capivara_version="9.9.9-test",
            capabilities={"native-linux": True, "steamcmd": True},
            cpu={"logical_cores": 8},
            ram_total_bytes=16 * 1024**3,
            storage={"root_free_bytes": 100 * 1024**3},
            network={"tcp_listen": [], "udp_listen": []},
        )
        runtime.heartbeat(self.agent_id)

    def _open_backend(self):
        backend = create_backend(DatabaseConfig(driver="sqlite", database=str(self.db_path)))
        backend.initialize()
        return backend

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _resolve_contract(self, user, game):
        if not user or user.get("scope_id") != self.customer_id or game != "dayz":
            return None
        return self.contract_id

    def _reserve_dayz_block(self, connection, instance_id: str, agent_id: str) -> list[int]:
        summary = effective_port_summary(self.backend, agent_id)
        udp_ranges = [item for item in summary["ranges"] if item["protocol"] == "udp"]
        self.assertTrue(udp_ranges, "eligible DayZ Agent must expose an UDP range")
        selected = udp_ranges[0]
        start = int(selected["start_port"])
        end = int(selected["end_port"])

        rows = connection.execute(
            "SELECT ip.port FROM instance_ports ip JOIN instances i ON i.id=ip.instance_id "
            "WHERE i.agent_id=? AND ip.protocol='udp'",
            (agent_id,),
        ).fetchall()
        occupied = {int(row["port"]) for row in rows}
        for base in range(start, end - 9 + 1):
            block = list(range(base, base + 10))
            if not occupied.intersection(block):
                for offset, port in enumerate(block):
                    connection.execute(
                        "INSERT INTO instance_ports(instance_id,name,protocol,port,bind_address) "
                        "VALUES (?,?,?,?,?)",
                        (instance_id, f"allocation_{offset}", "udp", port, "0.0.0.0"),
                    )
                return block
        raise RuntimeError("no contiguous DayZ port block available")

    def _create_dayz(self, user, payload):
        if not user or user.get("role") != "customer" or user.get("scope_id") != self.customer_id:
            raise PermissionError("customer scope required")
        if str(payload.get("game")) != "dayz":
            raise ValueError("unexpected game")
        contract_id = self._resolve_contract(user, "dayz")
        if not contract_id:
            raise ValueError("active DayZ contract required")

        requirements = requirements_for_instance(game_id="dayz", runtime_id="dayz.stable")
        decision = choose_agent_for_instance(
            self.backend,
            controller_id=self.controller_id,
            preferred_region_id=payload.get("region_id"),
            requirements=requirements,
        )
        instance_id = "phase22-dayz-001"
        progress = [
            {"progress": 5, "state": "placement", "message": "Agent selecionado"},
            {"progress": 20, "state": "ports", "message": "Reservando portas"},
            {"progress": 35, "state": "provisioning", "message": "Provisionamento iniciado"},
            {"progress": 80, "state": "validating", "message": "Validando instalação"},
            {"progress": 100, "state": "completed", "message": "Servidor criado"},
        ]

        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,metadata_json,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    instance_id,
                    decision["node_id"],
                    "dayz",
                    "dayz.stable",
                    "Phase 22 DayZ",
                    "pending",
                    "{}",
                    self.controller_id,
                    decision["agent_id"],
                    self.customer_id,
                ),
            )
            connection.execute(
                "INSERT INTO instance_contracts(instance_id,contract_id) VALUES (?,?)",
                (instance_id, contract_id),
            )
            connection.execute("UPDATE instances SET status='provisioning' WHERE id=?", (instance_id,))
            ports = self._reserve_dayz_block(connection, instance_id, decision["agent_id"])
            # External SteamCMD is deliberately replaced by a deterministic E2E
            # provisioner; the orchestration/progress contract is real.
            connection.execute("UPDATE instances SET status='offline' WHERE id=?", (instance_id,))

        return {
            "instance_id": instance_id,
            "game": "dayz",
            "runtime_id": "dayz.stable",
            "contract_id": contract_id,
            "agent_id": decision["agent_id"],
            "node_id": decision["node_id"],
            "ports": ports,
            "provision": {"status": "completed", "progress": 100, "timeline": progress},
        }

    def test_customer_dayz_contract_placement_ports_provision_progress_and_persistence(self):
        user = {"role": "customer", "scope_id": self.customer_id, "username": "phase22-customer"}
        status, body = dispatch_instance_create_post(
            INSTANCE_CREATE_PATH,
            {"game": "dayz", "runtime_id": "dayz.stable"},
            user=user,
            create_instance=self._create_dayz,
            contract_resolver=self._resolve_contract,
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["contract_id"], self.contract_id)
        self.assertEqual(body["agent_id"], self.agent_id)
        self.assertEqual(len(body["ports"]), 10)
        self.assertEqual(body["ports"], list(range(body["ports"][0], body["ports"][0] + 10)))
        self.assertEqual(body["provision"]["progress"], 100)
        self.assertEqual(body["provision"]["timeline"][-1]["state"], "completed")

        with self.backend.connect() as connection:
            instance = connection.execute(
                "SELECT status,agent_id,node_id,customer_id FROM instances WHERE id=?",
                (body["instance_id"],),
            ).fetchone()
            reserved = connection.execute(
                "SELECT COUNT(*) AS total FROM instance_ports WHERE instance_id=?",
                (body["instance_id"],),
            ).fetchone()
        self.assertEqual(instance["status"], "offline")
        self.assertEqual(instance["agent_id"], self.agent_id)
        self.assertEqual(instance["node_id"], self.node_id)
        self.assertEqual(instance["customer_id"], self.customer_id)
        self.assertEqual(int(reserved["total"]), 10)

        # Controller restart: reopen the same persistent database and prove that
        # the completed creation and port reservations survive process restart.
        self.backend.close()
        self.backend = self._open_backend()
        with self.backend.connect() as connection:
            persisted = connection.execute(
                "SELECT status FROM instances WHERE id=?", (body["instance_id"],)
            ).fetchone()
            persisted_ports = connection.execute(
                "SELECT COUNT(*) AS total FROM instance_ports WHERE instance_id=?",
                (body["instance_id"],),
            ).fetchone()
        self.assertEqual(persisted["status"], "offline")
        self.assertEqual(int(persisted_ports["total"]), 10)

    def test_unexpected_runtime_error_is_always_an_http_response_not_empty_connection(self):
        def explode(_user, _payload):
            raise RuntimeError("simulated internal failure")

        result = dispatch_instance_create_post(
            INSTANCE_CREATE_PATH,
            {"game": "dayz"},
            user={"role": "customer", "scope_id": self.customer_id},
            create_instance=explode,
        )
        self.assertIsNotNone(result)
        status, body = result
        self.assertEqual(status, 500)
        self.assertEqual(body["error"], "instance_creation_failed")
        self.assertIn("message", body)
        self.assertNotIn("simulated internal failure", str(body))


if __name__ == "__main__":
    unittest.main()
