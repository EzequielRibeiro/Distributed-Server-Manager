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
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="game-data-controller",
        )
        self.controller_id = str(identity["controller_id"])
        issued = AgentPairingRepository(self.backend).issue_token(
            controller_id=self.controller_id,
            ttl_seconds=300,
        )
        status, enrolled = dispatch_enroll(
            {
                "pairing_token": issued.token,
                "agent_id": "agent-game-data",
                "node_id": "node-game-data",
                "name": "Game Data Agent",
                "fingerprint": "sha256:game-data-agent",
                "hostname": "game-data-agent",
                "os": "linux",
                "architecture": "x86_64",
            },
            backend=self.backend,
        )
        self.assertEqual(status, 201)
        self.headers = {
            "X-Capivara-Agent-Credential": enrolled["credential_id"],
            "X-Capivara-Agent-Secret": enrolled["credential_secret"],
            "X-Capivara-Agent-Fingerprint": "sha256:game-data-agent",
        }
        status, heartbeat = dispatch_heartbeat(
            {"agent_id": "agent-game-data", "hostname": "game-data-agent"},
            headers=self.headers,
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(heartbeat["status"], "active")
        self.jobs = AgentGameDataRepository(self.backend)
        self.jobs.initialize()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    @staticmethod
    def selection():
        return {
            "schema_version": 2,
            "kind": "RuntimeSelection",
            "runtime_definition": "dayz.stable",
            "game": "dayz",
            "variant": "stable",
            "version": "current",
            "provider": "steam",
            "auth": "required",
            "install": {"package_id": 223350},
            "install_dir": "/opt/dsm/game-data/dayz/serverfiles",
            "executable": "DayZServer",
        }

    def test_repository_queues_and_tracks_agent_owned_job(self):
        created = self.jobs.enqueue(
            agent_id="agent-game-data",
            action="install",
            environment_id="dayz.stable",
            selector="current",
            selection=self.selection(),
            requested_by="admin",
        )
        self.assertEqual(created["status"], "queued")
        command = self.jobs.command_for_agent("agent-game-data")
        self.assertEqual(command["job_id"], created["job_id"])
        self.assertEqual(command["selection"]["install"]["package_id"], 223350)

        delivered = self.jobs.mark_delivered(created["job_id"])
        self.assertEqual(delivered["status"], "delivered")
        running = self.jobs.apply_result(
            "agent-game-data",
            {"job_id": created["job_id"], "status": "running", "progress": 35},
        )
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["progress"], 35)
        completed = self.jobs.apply_result(
            "agent-game-data",
            {"job_id": created["job_id"], "status": "completed", "progress": 100},
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress"], 100)
        self.assertIsNone(self.jobs.command_for_agent("agent-game-data"))

    def test_authenticated_heartbeat_delivers_and_acknowledges_job(self):
        created = self.jobs.enqueue(
            agent_id="agent-game-data",
            action="install",
            environment_id="dayz.stable",
            selector="current",
            selection=self.selection(),
        )
        status, delivered = dispatch_heartbeat(
            {"agent_id": "agent-game-data"},
            headers=self.headers,
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(delivered["game_data_command"]["job_id"], created["job_id"])
        self.assertEqual(delivered["game_data_state"]["status"], "delivered")

        status, completed = dispatch_heartbeat(
            {
                "agent_id": "agent-game-data",
                "game_data_result": {
                    "job_id": created["job_id"],
                    "status": "completed",
                    "progress": 100,
                    "target_path": "/var/lib/capivara-agent/game-data/dayz/serverfiles",
                },
            },
            headers=self.headers,
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["game_data_state"]["job_id"], created["job_id"])
        self.assertEqual(completed["game_data_state"]["status"], "completed")
        self.assertNotIn("game_data_command", completed)

    def test_dayz_selection_is_resolved_before_delivery(self):
        selection = prepare_runtime_selection(ROOT, "dayz.stable", "current")
        self.assertEqual(selection["kind"], "RuntimeSelection")
        self.assertEqual(selection["game"], "dayz")
        self.assertEqual(selection["provider"], "steam")
        self.assertEqual(selection["install"]["package_id"], "223350")

    def test_dashboard_and_agent_package_expose_game_data_contract(self):
        ui = (ROOT / "dashboard/web/game-data-orchestration.js").read_text(encoding="utf-8")
        shell = (ROOT / "dashboard/web/js/infrastructure-shell.js").read_text(encoding="utf-8")
        package = (ROOT / "release/build_agent_package.sh").read_text(encoding="utf-8")
        installer = (ROOT / "agents/linux/installer/install-agent.sh").read_text(encoding="utf-8")
        service = (ROOT / "systemd/dsm-dashboard.service").read_text(encoding="utf-8")
        self.assertIn('agent_id: agent.id', ui)
        self.assertIn('/api/agents/game-data/jobs?job_id=', ui)
        self.assertIn('/game-data-orchestration.js', shell)
        self.assertIn('agent/runtime/game_data_client.py', package)
        self.assertIn('agent/runtime/game_data_executor.py', package)
        self.assertIn('game_data_executor.py', installer)
        self.assertIn('dashboard/server_part14.py', service)


if __name__ == "__main__":
    unittest.main()
