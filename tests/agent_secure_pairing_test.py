#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for path in (ROOT, DATABASE, DASHBOARD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from agent_pairing_repository import (
    AgentCredentialInvalid,
    AgentPairingRepository,
    PairingTokenConsumed,
    PairingTokenExpired,
)
from agent_pairing_api import (
    authenticate_agent_identity,
    enroll_remote_agent,
    issue_pairing_token_for_user,
)
from core.agent_enrollment import enrollment_config


class AgentSecurePairingTest(unittest.TestCase):
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
        self.repository = AgentPairingRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_token_is_random_hashed_expiring_and_single_use(self):
        issued = self.repository.issue_token(controller_id="controller-main", ttl_seconds=300)
        self.assertTrue(issued.token.startswith("cap_pair_"))
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT token_hash,consumed_at FROM agent_pairing_tokens WHERE id=?",
                (issued.token_id,),
            ).fetchone()
        self.assertNotEqual(row[0], issued.token)
        self.assertIsNone(row[1])

        enrolled = self.repository.enroll(
            pairing_token=issued.token,
            agent_id="agent-1",
            node_id="node-1",
            name="Node 1",
            fingerprint="sha256:agent-one",
            hostname="node-1.example",
            os_name="Ubuntu 24.04",
            architecture="x86_64",
            capivara_version="1.4.3",
            address="203.0.113.10",
            public_key="ssh-ed25519 AAAA-test",
        )
        self.assertEqual(enrolled.controller_id, "controller-main")
        self.assertEqual(enrolled.status, "pairing")
        self.assertTrue(enrolled.credential_secret.startswith("cap_agent_"))

        with sqlite3.connect(self.database_path) as connection:
            token_row = connection.execute(
                "SELECT consumed_at FROM agent_pairing_tokens WHERE id=?",
                (issued.token_id,),
            ).fetchone()
            cred_row = connection.execute(
                "SELECT secret_hash,fingerprint,public_key FROM agent_credentials WHERE id=?",
                (enrolled.credential_id,),
            ).fetchone()
        self.assertIsNotNone(token_row[0])
        self.assertNotEqual(cred_row[0], enrolled.credential_secret)
        self.assertEqual(cred_row[1], "sha256:agent-one")
        self.assertEqual(cred_row[2], "ssh-ed25519 AAAA-test")

        with self.assertRaises(PairingTokenConsumed):
            self.repository.enroll(
                pairing_token=issued.token,
                agent_id="agent-replay",
                node_id="node-replay",
                name="Replay",
                fingerprint="sha256:replay",
            )

    def test_expired_token_is_rejected(self):
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        issued = self.repository.issue_token(
            controller_id="controller-main", ttl_seconds=60, now=now
        )
        with self.assertRaises(PairingTokenExpired):
            self.repository.enroll(
                pairing_token=issued.token,
                agent_id="agent-expired",
                node_id="node-expired",
                name="Expired",
                fingerprint="sha256:expired",
                now=now + timedelta(seconds=61),
            )

    def test_permanent_identity_authenticates_without_pairing_token(self):
        issued = self.repository.issue_token(controller_id="controller-main")
        enrolled = self.repository.enroll(
            pairing_token=issued.token,
            agent_id="agent-auth",
            node_id="node-auth",
            name="Auth Agent",
            fingerprint="sha256:auth",
        )
        identity = authenticate_agent_identity(
            self.backend,
            credential_id=enrolled.credential_id,
            credential_secret=enrolled.credential_secret,
            fingerprint="sha256:auth",
        )
        self.assertEqual(identity["role"], "agent")
        self.assertEqual(identity["agent_id"], "agent-auth")
        self.assertEqual(identity["controller_id"], "controller-main")

        with self.assertRaises(AgentCredentialInvalid):
            authenticate_agent_identity(
                self.backend,
                credential_id=enrolled.credential_id,
                credential_secret="wrong",
            )
        with self.assertRaises(AgentCredentialInvalid):
            authenticate_agent_identity(
                self.backend,
                credential_id=enrolled.credential_id,
                credential_secret=enrolled.credential_secret,
                fingerprint="sha256:other",
            )

    def test_controller_scoped_token_api_and_agent_install_contract(self):
        user = {"username": "controller", "role": "controller", "scope_id": "controller-main"}
        issued = issue_pairing_token_for_user(
            user,
            self.backend,
            {
                "controller_url": "https://controller.example/",
                "ttl_seconds": 300,
            },
        )
        config = enrollment_config(issued["controller_url"], issued["pairing_token"])
        self.assertEqual(config.controller_url, "https://controller.example")

        response = enroll_remote_agent(
            self.backend,
            {
                "pairing_token": config.pairing_token,
                "agent_id": "agent-api",
                "node_id": "node-api",
                "name": "Agent API",
                "fingerprint": "sha256:api",
            },
        )
        self.assertTrue(response["pairing_token_consumed"])
        self.assertEqual(response["status"], "pairing")
        self.assertIn("credential_secret", response["identity"])

        with self.assertRaises(PermissionError):
            issue_pairing_token_for_user(
                {"role": "customer", "scope_id": "customer-1"},
                self.backend,
                {"controller_id": "controller-main"},
            )


if __name__ == "__main__":
    unittest.main()
