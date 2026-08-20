#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_pairing_repository import AgentPairingRepository
from agent_port_repository import AgentPortRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from agent_runtime_repository import AgentRuntimeRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from infrastructure_doctor import InfrastructureDoctor
from infrastructure_doctor_api import infrastructure_doctor_for_user
from infrastructure_doctor_contract import build_infrastructure_doctor_payload
from location_admin_api import upsert_datacenter_for_user, upsert_region_for_user
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class Phase20InfrastructureDoctorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="controller", hostname="doctor-controller"
        )
        self.controller_id = identity["controller_id"]
        self.admin = {"role": "admin", "username": "admin"}
        upsert_region_for_user(
            self.admin, self.backend,
            {"id": "br-se", "name": "Brasil Sudeste", "country_code": "BR", "status": "active"},
        )
        upsert_datacenter_for_user(
            self.admin, self.backend,
            {"id": "horizon", "region_id": "br-se", "name": "Horizon", "status": "active"},
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _enroll(self, agent_id: str, fingerprint: str, *, address: str = "192.0.2.10"):
        issued = AgentPairingRepository(self.backend).issue_token(
            controller_id=self.controller_id, ttl_seconds=300
        )
        code, enrolled = dispatch_enroll(
            {
                "pairing_token": issued.token,
                "agent_id": agent_id,
                "node_id": "node-" + agent_id,
                "name": agent_id,
                "fingerprint": fingerprint,
                "hostname": agent_id,
                "os": "linux",
                "architecture": "x86_64",
                "capivara_version": "1.0.0",
                "address": address,
            }, backend=self.backend,
        )
        self.assertEqual(code, 201)
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO agent_locations(agent_id,datacenter_id,status) VALUES (?,?,?)",
                (agent_id, "horizon", "active"),
            )
        AgentPortRepository(self.backend).set_ranges(
            agent_id,
            protocols=("tcp", "udp"),
            start_port=24000,
            end_port=24999,
        )
        code, heartbeat = dispatch_heartbeat(
            {
                "agent_id": agent_id,
                "hostname": agent_id,
                "os": "linux",
                "architecture": "x86_64",
                "capivara_version": "1.0.0",
                "address": address,
                "fingerprint": fingerprint,
                "capabilities": {"native-linux": True},
                "network": {"tcp_listen": [], "udp_listen": []},
            },
            headers={
                "X-Capivara-Agent-Credential": enrolled["credential_id"],
                "X-Capivara-Agent-Secret": enrolled["credential_secret"],
                "X-Capivara-Agent-Fingerprint": fingerprint,
            },
            backend=self.backend,
        )
        self.assertEqual(code, 200)
        return enrolled, heartbeat

    def test_healthy_infrastructure_is_ready(self):
        self._enroll("agent-one", "sha256:one")
        result = InfrastructureDoctor(self.backend).diagnose()
        self.assertTrue(result["ready"])
        statuses = {item["label"]: item["status"] for item in result["summary"]}
        self.assertEqual(statuses["Controller"], "OK")
        self.assertEqual(statuses["Agents"], "OK")
        self.assertEqual(statuses["Locations"], "OK")
        self.assertEqual(statuses["Regions"], "OK")
        self.assertEqual(statuses["Datacenters"], "OK")
        self.assertEqual(statuses["Port allocation"], "OK")
        self.assertEqual(statuses["Placement"], "READY")

    def test_public_contract_is_stable_and_healthy(self):
        self._enroll("agent-one", "sha256:one")
        result = build_infrastructure_doctor_payload(self.backend)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["kind"], "CapivaraInfrastructureDoctor")
        self.assertEqual(result["scope"], "infrastructure")
        self.assertEqual(result["status"], "healthy")
        self.assertTrue(result["ready"])
        self.assertTrue(result["generated_at"].endswith("Z"))
        self.assertIn("summary", result)
        self.assertIn("findings", result)
        self.assertIn("placement", result)
        self.assertIn("repairs", result)

    def test_dashboard_api_uses_public_contract_and_rejects_customer(self):
        self._enroll("agent-one", "sha256:one")
        result = infrastructure_doctor_for_user(self.admin, self.backend)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["scope"], "infrastructure")
        self.assertFalse(result["reconcile_mode"])
        with self.assertRaises(PermissionError):
            infrastructure_doctor_for_user(
                {"role": "customer", "username": "customer"},
                self.backend,
            )

    def test_default_doctor_is_strictly_observational(self):
        self._enroll("agent-one", "sha256:one")
        stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE agent_runtime_inventory SET last_seen=?,health_status='online' WHERE agent_id='agent-one'",
                (stale,),
            )

        with patch.object(
            self.backend,
            "initialize",
            side_effect=AssertionError("doctor must not initialize or migrate the database"),
        ), patch.object(
            AgentRuntimeRepository,
            "refresh_health",
            side_effect=AssertionError("doctor must not persist derived Agent health"),
        ):
            result = InfrastructureDoctor(self.backend).diagnose()

        self.assertFalse(result["reconcile_mode"])
        self.assertEqual(result["repairs"], [])
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT health_status,last_seen FROM agent_runtime_inventory WHERE agent_id='agent-one'"
            ).fetchone()
        self.assertEqual(row["health_status"], "online")
        self.assertEqual(row["last_seen"], stale)

    def test_duplicate_fingerprint_is_blocking_and_never_auto_repaired(self):
        self._enroll("agent-one", "sha256:duplicate", address="192.0.2.10")
        self._enroll("agent-two", "sha256:duplicate", address="192.0.2.11")
        result = InfrastructureDoctor(self.backend).diagnose(reconcile=True)
        duplicate = [item for item in result["findings"] if item["code"] == "duplicate_agent_identity"]
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(duplicate[0]["severity"], "critical")
        self.assertFalse(duplicate[0]["repairable"])
        self.assertFalse(result["ready"])

    def test_disabled_region_blocks_placement_without_touching_instances(self):
        self._enroll("agent-one", "sha256:one")
        with self.backend.transaction() as connection:
            connection.execute("UPDATE regions SET status='disabled' WHERE id='br-se'")
        result = InfrastructureDoctor(self.backend).diagnose()
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("region_disabled_for_agent", codes)
        self.assertIn("placement_not_ready", codes)
        self.assertFalse(result["ready"])

    def test_reconcile_refreshes_stale_health_only(self):
        self._enroll("agent-one", "sha256:one")
        stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE agent_runtime_inventory SET last_seen=?,health_status='online' WHERE agent_id='agent-one'",
                (stale,),
            )
        result = InfrastructureDoctor(self.backend).diagnose(reconcile=True)
        actions = [item for item in result["repairs"] if item["action"] == "refresh_agent_health"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["agent_id"], "agent-one")
        self.assertEqual(actions[0]["to"], "offline")
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT health_status FROM agent_runtime_inventory WHERE agent_id='agent-one'"
            ).fetchone()
        self.assertEqual(row["health_status"], "offline")

    def test_changed_ip_is_reconciled_by_authenticated_heartbeat(self):
        enrolled, _ = self._enroll("agent-one", "sha256:one", address="192.0.2.10")
        code, _ = dispatch_heartbeat(
            {
                "agent_id": "agent-one",
                "hostname": "agent-one",
                "os": "linux",
                "architecture": "x86_64",
                "capivara_version": "1.0.0",
                "address": "198.51.100.25",
                "fingerprint": "sha256:one",
                "capabilities": {"native-linux": True},
                "network": {"tcp_listen": [], "udp_listen": []},
            },
            headers={
                "X-Capivara-Agent-Credential": enrolled["credential_id"],
                "X-Capivara-Agent-Secret": enrolled["credential_secret"],
                "X-Capivara-Agent-Fingerprint": "sha256:one",
            }, backend=self.backend,
        )
        self.assertEqual(code, 200)
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT address FROM agent_runtime_inventory WHERE agent_id='agent-one'"
            ).fetchone()
        self.assertEqual(row["address"], "198.51.100.25")
        result = InfrastructureDoctor(self.backend).diagnose()
        self.assertNotIn("duplicate_agent_identity", {item["code"] for item in result["findings"]})


if __name__ == "__main__":
    unittest.main()
