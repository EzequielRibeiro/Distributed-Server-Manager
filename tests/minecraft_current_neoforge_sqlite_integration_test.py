#!/usr/bin/env python3
"""Real temporary SQLite integration for current NeoForge audit persistence."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
for folder in ("database","dashboard"):
    sys.path.insert(0,str(ROOT/folder))
from backend import DatabaseConfig
from backends.sqlite_backend import SQLiteBackend
from minecraft_current_neoforge_event_persistence import persist_current_neoforge_attestations
from universal_event_repository import UniversalEventRepository
from minecraft_current_neoforge_assessment import assess_current_neoforge
from minecraft_recovery_customer_projection import visible_provision_after_recovery

class CurrentNeoForgeSQLiteIntegrationTest(unittest.TestCase):
    def test_real_sqlite_audit_is_idempotent_and_separate_from_historical_recovery(self):
        with tempfile.TemporaryDirectory(prefix="capivara-neoforge-") as temp:
            backend=SQLiteBackend(DatabaseConfig(driver="sqlite",database=str(Path(temp)/"test.db")))
            try:
                backend.initialize()
                claim={"kind":"MinecraftNeoForgeCurrentAttestation",
                       "agent_id":"isolated-agent","instance_id":"isolated-mc005",
                       "loader_version":"26.1.2.94","observed_at":"2026-10-24T13:00:00Z"}
                self.assertEqual(persist_current_neoforge_attestations(backend,[claim])["created"],1)
                self.assertEqual(persist_current_neoforge_attestations(backend,[claim])["created"],0)
                events=UniversalEventRepository(backend).list_events(
                    limit=10,event_type="MINECRAFT_NEOFORGE_CURRENT_VERIFIED",
                    agent_id="isolated-agent",instance_id="isolated-mc005")
                self.assertEqual(len(events),1)
                self.assertEqual(events[0]["data"]["proof_scope"],"current_runtime_only")
                historical=UniversalEventRepository(backend).list_events(
                    limit=10,event_type="MINECRAFT_SERVERPACK_MIGRATION_RECOVERED",
                    agent_id="isolated-agent",instance_id="isolated-mc005")
                self.assertEqual(historical,[])
                failed={"status":"failed","agent_id":"isolated-agent",
                        "instance_id":"isolated-mc005","completed_at":"2026-10-23T20:00:00Z","progress":99}
                health={"instance_id":"isolated-mc005","observed_state":"running",
                        "reconcile_status":"healthy","health":"healthy",
                        "reported_at":"2026-10-24T13:01:00Z"}
                decision=assess_current_neoforge(
                    agent_id="isolated-agent",instance_id="isolated-mc005",
                    failed_provision=failed,attestation_events=events,runtime_health=health)
                self.assertEqual(decision["status"],"current_runtime_verified")
                self.assertFalse(decision["allow_clear_previous_failure"])
                visible=visible_provision_after_recovery(
                    failed,{"status":"missing_recovery_evidence","current_neoforge":decision})
                self.assertEqual(visible["status"],"failed")
                self.assertEqual(visible["progress"],99)
                self.assertEqual(visible["current_runtime_diagnosis"],
                                 "running_verified_installation_history_unresolved")
            finally:
                backend.close()

if __name__=="__main__":
    unittest.main()
