#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_runtime_repository import AgentRuntimeRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from content_platform import ContentValidationError, normalize_assignment
from content_repository import ContentRepository


class ContentProviderSecurityTest(unittest.TestCase):
    def test_nested_credentials_and_commands_are_rejected(self):
        base = {
            "agent_id": "agent-c4",
            "instance_id": "instance-c4",
            "content_id": "workshop-one",
            "game_id": "example",
            "content_type": "workshop",
            "provider": "steam-workshop",
        }
        with self.assertRaises(ContentValidationError):
            normalize_assignment({
                **base,
                "artifact": {"package_id": "221100:123456", "auth": {"password": "secret"}},
            })
        with self.assertRaises(ContentValidationError):
            normalize_assignment({
                **base,
                "artifact": {"package_id": "221100:123456", "metadata": [{"script": "echo bad"}]},
            })


class ContentProviderPreflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.tmp.name) / "capivara.db"),
        ))
        self.backend.initialize()
        with self.backend.transaction() as c:
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)", ("node-controller", "Controller", "controller"))
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)", ("node-agent", "Agent", "agent"))
            c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)", ("controller-c4", "node-controller", "C4"))
            c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)", ("agent-c4", "controller-c4", "node-agent", "Agent C4", "active"))
            customer = c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)", ("controller-c4", "Customer C4"))
            c.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",
                ("instance-c4", "node-agent", "example", "C4 Instance", "stopped", "controller-c4", "agent-c4", int(customer.lastrowid)),
            )
        self.repo = ContentRepository(self.backend)
        self.repo.initialize()

    def tearDown(self):
        self.backend.close()
        self.tmp.cleanup()

    def payload(self, provider="http"):
        return {
            "instance_id": "instance-c4",
            "content_id": "content-one",
            "game_id": "example",
            "content_type": "mod",
            "desired_state": "installed",
            "version": "1.0",
            "provider": provider,
            "artifact": {"url": "https://example.invalid/content.bin"},
        }

    def test_legacy_agent_without_provider_contract_remains_compatible(self):
        result = self.repo.put(self.payload())
        self.assertTrue(result["changed"])

    def test_advertised_provider_contract_rejects_unsupported_provider(self):
        runtime = AgentRuntimeRepository(self.backend)
        runtime.initialize()
        runtime.upsert_inventory(
            agent_id="agent-c4",
            capabilities={
                "content_provider_contract": 1,
                "content_providers": ["local", "steam-workshop"],
            },
        )
        with self.assertRaisesRegex(ContentValidationError, "does not support content provider: http"):
            self.repo.put(self.payload("http"))

    def test_advertised_provider_contract_accepts_supported_provider(self):
        runtime = AgentRuntimeRepository(self.backend)
        runtime.initialize()
        runtime.upsert_inventory(
            agent_id="agent-c4",
            capabilities={
                "content_provider_contract": 1,
                "content_providers": ["http", "steam-workshop"],
            },
        )
        result = self.repo.put(self.payload("http"))
        self.assertTrue(result["changed"])


if __name__ == "__main__":
    unittest.main()
