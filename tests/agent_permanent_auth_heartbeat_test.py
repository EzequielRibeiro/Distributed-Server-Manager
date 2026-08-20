#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for path in (ROOT, DATABASE, DASHBOARD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from agent_pairing_repository import AgentPairingRepository
from agent_authenticated_api import authenticated_agent_heartbeat


class AgentPermanentHeartbeatTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.database_path))
        )
        self.backend.initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role,status,metadata_json) VALUES (?,?,?,?,?)",
                ("controller-node", "Controller", "controller", "active", "{}"),
            )
            connection.execute(
                "INSERT INTO controllers(id,node_id,name,status,metadata_json) VALUES (?,?,?,?,?)",
                ("controller-main", "controller-node", "Controller", "active", "{}"),
            )
            connection.commit()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_heartbeat_uses_permanent_identity_after_enrollment(self):
        repository = AgentPairingRepository(self.backend)
        token = repository.issue_token(controller_id="controller-main")
        identity = repository.enroll(
            pairing_token=token.token,
            agent_id="agent-heartbeat",
            node_id="node-heartbeat",
            name="Heartbeat Agent",
            fingerprint="sha256:heartbeat",
        )

        result = authenticated_agent_heartbeat(
            self.backend,
            credential_id=identity.credential_id,
            credential_secret=identity.credential_secret,
            fingerprint="sha256:heartbeat",
            payload={
                "agent_id": "agent-heartbeat",
                "hostname": "edge-01",
                "os": "Ubuntu 24.04",
                "architecture": "x86_64",
                "capivara_version": "1.4.3",
            },
        )
        self.assertEqual(result["agent_id"], "agent-heartbeat")
        self.assertEqual(result["health_status"], "online")
        self.assertTrue(result["last_seen"])

        with sqlite3.connect(self.database_path) as connection:
            token_value = connection.execute(
                "SELECT consumed_at FROM agent_pairing_tokens WHERE id=?",
                (token.token_id,),
            ).fetchone()[0]
            runtime = connection.execute(
                "SELECT health_status,last_seen FROM agent_runtime_inventory WHERE agent_id=?",
                ("agent-heartbeat",),
            ).fetchone()
        self.assertTrue(token_value)
        self.assertEqual(runtime[0], "online")
        self.assertTrue(runtime[1])


if __name__ == "__main__":
    unittest.main()
