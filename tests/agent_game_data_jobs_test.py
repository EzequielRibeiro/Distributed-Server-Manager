#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_game_data_api import prepare_runtime_selection
from agent_game_data_http import (
    GAME_DATA_FILES_PATH,
    GAME_DATA_JOBS_PATH,
    GAME_DATA_OPERATION_PATH,
    dispatch_agent_game_data_get,
)
from agent_game_data_repository import AgentGameDataRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentGameDataJobsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        identity = installation_profile_identity(RegistryRepository(self.backend), profile="controller", hostname="game-data-controller")
        issued = AgentPairingRepository(self.backend).issue_token(controller_id=str(identity["controller_id"]), ttl_seconds=300)
        status, enrolled = dispatch_enroll({"pairing_token":issued.token,"agent_id":"agent-game-data","node_id":"node-game-data","name":"Game Data Agent","fingerprint":"sha256:game-data-agent","hostname":"game-data-agent","os":"linux","architecture":"x86_64"}, backend=self.backend)
        self.assertEqual(status, 201)
        self.headers = {"X-Capivara-Agent-Credential":enrolled["credential_id"],"X-Capivara-Agent-Secret":enrolled["credential_secret"],"X-Capivara-Agent-Fingerprint":"sha256:game-data-agent"}
        status, heartbeat = dispatch_heartbeat({"agent_id":"agent-game-data","hostname":"game-data-agent"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200); self.assertEqual(heartbeat["status"], "active")
        self.jobs = AgentGameDataRepository(self.backend); self.jobs.initialize()

    def tearDown(self):
        self.backend.close(); self.temp.cleanup()

    @staticmethod
    def selection():
        return {"schema_version":2,"kind":"RuntimeSelection","runtime_definition":"dayz.stable","game":"dayz","variant":"stable","version":"current","provider":"steam","auth":"required","install":{"package_id":223350},"install_dir":"/opt/dsm/game-data/dayz/serverfiles","executable":"DayZServer"}

    def test_repository_queues_and_tracks_agent_owned_job(self):
        created = self.jobs.enqueue(agent_id="agent-game-data",action="install",environment_id="dayz.stable",selector="current",selection=self.selection(),requested_by="admin")
        self.assertEqual(created["status"], "queued")
        command = self.jobs.command_for_agent("agent-game-data")
        self.assertEqual(command["job_id"], created["job_id"]); self.assertEqual(command["selection"]["install"]["package_id"], 223350)
        delivered = self.jobs.mark_delivered(created["job_id"]); self.assertEqual(delivered["status"], "delivered")
        running = self.jobs.apply_result("agent-game-data", {"job_id":created["job_id"],"status":"running","progress":35}); self.assertEqual(running["status"], "running")
        completed = self.jobs.apply_result("agent-game-data", {"job_id":created["job_id"],"status":"completed","progress":100}); self.assertEqual(completed["status"], "completed")
        self.assertIsNone(self.jobs.command_for_agent("agent-game-data"))

    def test_file_job_delivers_operation(self):
        selection = self.selection(); selection["_file_operation"] = {"action":"list","path":""}
        created = self.jobs.enqueue(agent_id="agent-game-data",action="file-list",environment_id="dayz.stable",selector="current",selection=selection,requested_by="admin")
        command = self.jobs.command_for_agent("agent-game-data")
        self.assertEqual(command["job_id"], created["job_id"])
        self.assertEqual(command["file_operation"], {"action":"list","path":""})

    def test_authenticated_heartbeat_delivers_and_acknowledges_job(self):
        created = self.jobs.enqueue(agent_id="agent-game-data",action="install",environment_id="dayz.stable",selector="current",selection=self.selection())
        status, delivered = dispatch_heartbeat({"agent_id":"agent-game-data"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200); self.assertEqual(delivered["game_data_command"]["job_id"], created["job_id"]); self.assertEqual(delivered["game_data_state"]["status"], "delivered")
        status, completed = dispatch_heartbeat({"agent_id":"agent-game-data","game_data_result":{"job_id":created["job_id"],"status":"completed","progress":100,"target_path":"/var/lib/capivara-agent/game-data/dayz/serverfiles"}}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200); self.assertEqual(completed["game_data_state"]["status"], "completed"); self.assertNotIn("game_data_command", completed)

    def test_http_status_is_admin_only_and_transport_neutral(self):
        created = self.jobs.enqueue(agent_id="agent-game-data",action="verify",environment_id="dayz.stable",selector="current",selection=self.selection())
        status, body = dispatch_agent_game_data_get(GAME_DATA_JOBS_PATH,f"job_id={created['job_id']}",user={"role":"admin","username":"admin"},backend=self.backend)
        self.assertEqual(status, 200); self.assertEqual(body["job_id"], created["job_id"])
        status, _ = dispatch_agent_game_data_get(GAME_DATA_JOBS_PATH,f"job_id={created['job_id']}",user={"role":"customer","username":"customer"},backend=self.backend)
        self.assertEqual(status, 403)
        self.assertEqual(GAME_DATA_OPERATION_PATH, "/api/agents/game-data")
        self.assertEqual(GAME_DATA_FILES_PATH, "/api/agents/game-data/files")

    def test_dayz_selection_is_resolved_before_delivery(self):
        selection = prepare_runtime_selection(ROOT, "dayz.stable", "current")
        self.assertEqual(selection["kind"], "RuntimeSelection"); self.assertEqual(selection["game"], "dayz"); self.assertEqual(selection["provider"], "steam"); self.assertEqual(str(selection["install"]["package_id"]), "223350")

    def test_modern_integration_is_layered_without_growing_legacy_server(self):
        self.assertTrue((ROOT / "dashboard/server_part14.py").is_file())
        self.assertTrue((ROOT / "dashboard/server_part15.py").is_file())
        self.assertTrue((ROOT / "dashboard/server_part16.py").is_file())
        server = (ROOT / "dashboard/server_part13.py").read_text(encoding="utf-8")
        self.assertIn("dispatch_agent_game_data_get", server); self.assertIn("dispatch_agent_game_data_post", server)
        latest = (ROOT / "dashboard/server_part16.py").read_text(encoding="utf-8")
        self.assertIn("GAME_DATA_FILES_PATH", latest)
        package = (ROOT / "release/build_agent_package.sh").read_text(encoding="utf-8")
        self.assertIn("agent/runtime/local_cli.py", package); self.assertIn("agent/runtime/game_data_client.py", package); self.assertIn("agent/runtime/game_data_executor.py", package); self.assertIn("game_data_files.py", package)
        for backend in ("sqlite", "postgresql", "mysql", "mariadb"):
            schema = (ROOT / "database" / "schemas" / f"{backend}.sql").read_text(); self.assertIn("agent_game_data_jobs", schema)


if __name__ == "__main__":
    unittest.main()
