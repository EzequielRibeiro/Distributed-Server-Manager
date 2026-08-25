#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    sys.path.insert(0, str(path))

from agent_installation_api import create_agent_installation_for_user, agent_installation_status_for_user
from agent_location_safety import safely_set_agent_location_for_user
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from location_admin_api import upsert_datacenter_for_user, upsert_region_for_user
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentDashboardPhase14And15Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="controller", hostname="phase14-controller"
        )
        self.controller_id = identity["controller_id"]
        self.admin = {"role": "admin", "username": "admin"}
        self.controller = {"role": "controller", "scope_id": self.controller_id, "username": "controller"}
        upsert_region_for_user(self.admin, self.backend, {"id": "br-se", "name": "Brasil Sudeste", "country_code": "BR"})
        upsert_datacenter_for_user(self.admin, self.backend, {"id": "horizon", "region_id": "br-se", "name": "Horizon"})
        upsert_datacenter_for_user(self.admin, self.backend, {"id": "horizon-2", "region_id": "br-se", "name": "Horizon 2"})

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_github_installation_tracks_waiting_pairing_and_online(self):
        installation = create_agent_installation_for_user(self.controller, self.backend, {
            "platform": "linux", "method": "github", "region_id": "br-se", "datacenter_id": "horizon",
            "controller_url": "https://controller.example",
        })
        self.assertEqual(installation["state"], "waiting")
        self.assertIn("/agent/install.sh", installation["instruction"])
        status = agent_installation_status_for_user(self.controller, self.backend, installation["installation_id"])
        self.assertEqual(status["state"], "waiting")

        token = installation["instruction"].split("--pairing-token ", 1)[1].split()[0]
        code, enrolled = dispatch_enroll({
            "pairing_token": token, "agent_id": "agent-remote-1", "node_id": "node-remote-1",
            "name": "Remote 1", "fingerprint": "sha256:remote1", "hostname": "remote1",
            "os": "linux", "architecture": "x86_64",
        }, backend=self.backend)
        self.assertEqual(code, 201)
        self.assertTrue(enrolled["installation_tracking_bound"])
        status = agent_installation_status_for_user(self.controller, self.backend, installation["installation_id"])
        self.assertEqual(status["state"], "pairing")
        self.assertEqual(status["agent_id"], "agent-remote-1")

        code, heartbeat = dispatch_heartbeat(
            {"agent_id": "agent-remote-1", "hostname": "remote1", "capivara_version": "1.0.0"},
            headers={
                "X-Capivara-Agent-Credential": enrolled["credential_id"],
                "X-Capivara-Agent-Secret": enrolled["credential_secret"],
                "X-Capivara-Agent-Fingerprint": "sha256:remote1",
            }, backend=self.backend,
        )
        self.assertEqual(code, 200)
        self.assertEqual(heartbeat["status"], "active")
        self.assertEqual(heartbeat["update_state"]["installed_version"], "1.0.0")
        status = agent_installation_status_for_user(self.controller, self.backend, installation["installation_id"])
        self.assertEqual(status["state"], "online")

        with self.backend.connect() as connection:
            row = connection.execute("SELECT datacenter_id FROM agent_locations WHERE agent_id='agent-remote-1'").fetchone()
        self.assertEqual(row["datacenter_id"], "horizon")

    def test_local_method_uses_same_pairing_without_github_instruction(self):
        installation = create_agent_installation_for_user(self.controller, self.backend, {
            "platform": "linux", "method": "local", "region_id": "br-se", "datacenter_id": "horizon",
            "controller_url": "https://controller.example",
        })
        self.assertIn("./install-agent.sh", installation["instruction"])
        self.assertNotIn("github.com", installation["instruction"].lower())

    def test_windows_uses_same_pairing_flow(self):
        installation = create_agent_installation_for_user(self.controller, self.backend, {
            "platform": "windows", "method": "github", "region_id": "br-se", "datacenter_id": "horizon",
            "controller_url": "https://controller.example",
        })
        self.assertEqual(installation["platform"], "windows")
        self.assertIn("/agent/install.ps1", installation["instruction"])
        self.assertIn("PairingToken", installation["instruction"])
        status = agent_installation_status_for_user(self.controller, self.backend, installation["installation_id"])
        self.assertEqual(status["platform"], "windows")
        self.assertEqual(status["state"], "waiting")

    def test_location_change_preserves_existing_instance(self):
        installation = create_agent_installation_for_user(self.controller, self.backend, {
            "platform": "linux", "method": "github", "region_id": "br-se", "datacenter_id": "horizon",
            "controller_url": "https://controller.example",
        })
        token = installation["instruction"].split("--pairing-token ", 1)[1].split()[0]
        _, enrolled = dispatch_enroll({
            "pairing_token": token, "agent_id": "agent-safe", "node_id": "node-safe", "name": "Safe",
            "fingerprint": "sha256:safe", "hostname": "safe", "os": "linux", "architecture": "x86_64",
        }, backend=self.backend)
        with self.backend.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO customers(controller_id,name,status,metadata_json) VALUES (?,?,?,?)",
                (self.controller_id, "Customer", "active", "{}"),
            )
            customer_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,metadata_json,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                ("instance-safe", "node-safe", "minecraft", "Instance", "offline", "{}", self.controller_id, "agent-safe", customer_id),
            )
        result = safely_set_agent_location_for_user(self.controller, self.backend, {
            "agent_id": "agent-safe", "datacenter_id": "horizon-2", "public_host": "games.example",
            "latitude": -22.56, "longitude": -47.40, "status": "active",
        })
        self.assertEqual(result["instances_preserved"], 1)
        self.assertEqual(result["instance_ids_preserved"], ["instance-safe"])
        with self.backend.connect() as connection:
            row = connection.execute("SELECT agent_id,node_id FROM instances WHERE id='instance-safe'").fetchone()
        self.assertEqual((row["agent_id"], row["node_id"]), ("agent-safe", "node-safe"))


if __name__ == "__main__":
    unittest.main()
