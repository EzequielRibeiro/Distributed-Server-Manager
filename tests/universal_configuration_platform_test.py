#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard", ROOT / "agents" / "linux" / "runtime"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_heartbeat_api import record_agent_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from configuration_client import apply_configuration_commands, configuration_state
from configuration_platform import ConfigurationValidationError, deep_merge, normalize_configuration
from configuration_repository import ConfigurationRepository


class ConfigurationContractTest(unittest.TestCase):
    def test_normalizes_and_checksums(self):
        value = normalize_configuration({
            "scope_type": "agent",
            "scope_id": "agent-c2",
            "namespace": "runtime.limits",
            "value": {"cpu": {"quota": 80}, "enabled": True},
        })
        self.assertEqual(value["kind"], "CapivaraConfiguration")
        self.assertEqual(value["namespace"], "runtime.limits")
        self.assertEqual(len(value["checksum"]), 64)

    def test_rejects_raw_secrets_and_accepts_references(self):
        with self.assertRaises(ConfigurationValidationError):
            normalize_configuration({
                "scope_type": "global", "namespace": "mail.smtp", "value": {"password": "plaintext"}
            })
        accepted = normalize_configuration({
            "scope_type": "global", "namespace": "mail.smtp", "value": {"password_ref": "secret://smtp/main"}
        })
        self.assertEqual(accepted["value"]["password_ref"], "secret://smtp/main")

    def test_deep_merge_is_recursive(self):
        self.assertEqual(
            deep_merge({"runtime": {"cpu": 50, "ram": 1024}}, {"runtime": {"cpu": 80}}),
            {"runtime": {"cpu": 80, "ram": 1024}},
        )


class ConfigurationRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        with self.backend.transaction() as connection:
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)", ("node-controller", "Controller", "controller"))
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)", ("node-agent", "Agent", "agent"))
            connection.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)", ("controller-c2", "node-controller", "C2"))
            connection.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)", ("agent-c2", "controller-c2", "node-agent", "Agent C2", "active"))
        self.repo = ConfigurationRepository(self.backend)
        self.repo.initialize()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_revisions_are_immutable_and_noop_is_idempotent(self):
        first = self.repo.put({"scope_type": "global", "namespace": "runtime.policy", "value": {"restart": {"max_attempts": 3}}}, updated_by="test")
        same = self.repo.put({"scope_type": "global", "namespace": "runtime.policy", "value": {"restart": {"max_attempts": 3}}}, updated_by="test")
        second = self.repo.put({"scope_type": "global", "namespace": "runtime.policy", "value": {"restart": {"max_attempts": 5}}}, updated_by="test")
        self.assertTrue(first["changed"])
        self.assertFalse(same["changed"])
        self.assertEqual(second["configuration"]["revision"], 2)
        history = self.repo.history(first["configuration"]["configuration_id"])
        self.assertEqual([row["revision"] for row in history], [2, 1])

    def test_agent_scope_overrides_global_scope(self):
        self.repo.put({"scope_type": "global", "namespace": "runtime.policy", "value": {"restart": {"max_attempts": 3, "backoff": 10}, "logs": True}})
        self.repo.put({"scope_type": "agent", "scope_id": "agent-c2", "namespace": "runtime.policy", "value": {"restart": {"max_attempts": 7}}})
        resolved = self.repo.resolve_for_agent("agent-c2")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["value"]["restart"], {"max_attempts": 7, "backoff": 10})
        self.assertTrue(resolved[0]["value"]["logs"])
        self.assertEqual(len(resolved[0]["configuration_refs"]), 2)

    def test_heartbeat_distributes_configuration_and_records_ack(self):
        stored = self.repo.put({"scope_type": "agent", "scope_id": "agent-c2", "namespace": "agent.runtime", "value": {"reconcile_interval_seconds": 20}})["configuration"]
        first = record_agent_heartbeat("agent-c2", {"agent_id": "agent-c2"}, backend=self.backend)
        self.assertEqual(first["configuration_count"], 1)
        command = first["configuration_commands"][0]
        ref = command["configuration_refs"][0]
        self.assertEqual(ref["configuration_id"], stored["configuration_id"])
        second = record_agent_heartbeat("agent-c2", {
            "agent_id": "agent-c2",
            "configuration_state": [{
                "configuration_id": ref["configuration_id"],
                "desired_revision": ref["revision"],
                "applied_revision": ref["revision"],
                "status": "applied",
                "applied_checksum": ref["checksum"],
            }],
        }, backend=self.backend)
        self.assertEqual(second["health_status"], "online")
        with self.backend.connect() as connection:
            row = connection.execute("SELECT * FROM agent_configuration_state WHERE agent_id=? AND configuration_id=?", ("agent-c2", ref["configuration_id"])).fetchone()
        self.assertEqual(row["status"], "applied")
        self.assertEqual(row["applied_revision"], 1)


class AgentConfigurationClientTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
        os.environ["CAPIVARA_AGENT_STATE_DIR"] = self.temp.name

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("CAPIVARA_AGENT_STATE_DIR", None)
        else:
            os.environ["CAPIVARA_AGENT_STATE_DIR"] = self.previous
        self.temp.cleanup()

    def test_applies_atomically_and_reports_refs(self):
        reports = apply_configuration_commands([{
            "namespace": "runtime.policy",
            "target_type": "agent",
            "target_id": "agent-c2",
            "revision": "abc",
            "checksum": "digest",
            "value": {"enabled": True},
            "configuration_refs": [{"configuration_id": "cfg-1", "revision": 3, "checksum": "hash-3"}],
        }])
        self.assertEqual(reports[0]["configuration_id"], "cfg-1")
        self.assertEqual(configuration_state()[0]["applied_revision"], 3)
        applied = Path(self.temp.name) / "managed-configuration" / "agent" / "agent-c2" / "runtime.policy.json"
        self.assertTrue(applied.is_file())


if __name__ == "__main__":
    unittest.main()
