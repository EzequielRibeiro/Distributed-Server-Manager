#!/usr/bin/env python3
"""Hybrid current proof collection cannot revise provisioning or claim recovery."""
import sys, tempfile, unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"dashboard",ROOT/"dashboard/workers",ROOT/"database"):
 sys.path.insert(0,str(path))
from hybrid_agent_worker import process_hybrid_current_neoforge_attestation_cycle
class HybridCurrentAttestationTests(unittest.TestCase):
 def test_missing_environment_fails_closed_without_mutations(self):
  with patch("hybrid_agent_worker._instance_runtime_module",side_effect=RuntimeError("offline")):
   result=process_hybrid_current_neoforge_attestation_cycle(object(),Path("/nonexistent/dsm"),"agent")
  self.assertEqual(result,{"status":"unavailable","verified":0})
 def test_owned_hybrid_instance_publishes_only_current_attestation(self):
  claim={"kind":"MinecraftNeoForgeCurrentAttestation","agent_id":"agent",
         "instance_id":"mc005","loader_version":"26.1.2.94",
         "observed_at":"2026-10-24T10:00:00Z","verified":True}
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/"runtime/hybrid-agent-state/instances"
   path.mkdir(parents=True)
   (path/"mc005.json").write_text("{}")
   with patch("hybrid_agent_worker._instance_runtime_module",return_value=SimpleNamespace(get_instance=lambda _:{})), \
        patch("minecraft_current_neoforge_collector.collect_current_neoforge_attestations",return_value=[claim]), \
        patch("minecraft_recovery_heartbeat_claims.owned_instance_ids_for_agent",return_value={"mc005"}), \
        patch("minecraft_current_neoforge_event_persistence.persist_current_neoforge_attestations",return_value={"accepted":1,"created":1}) as persist:
    result=process_hybrid_current_neoforge_attestation_cycle(object(),Path(temp),"agent")
  self.assertEqual(result,{"status":"audited","verified":1,"accepted":1,"created":1})
  approved=persist.call_args.args[1]
  self.assertEqual(len(approved),1)
  self.assertNotIn("recovered_at",approved[0])
 def test_unowned_instance_does_not_persist(self):
  claim={"kind":"MinecraftNeoForgeCurrentAttestation","agent_id":"agent",
         "instance_id":"mc005","loader_version":"26.1.2.94",
         "observed_at":"2026-10-24T10:00:00Z","verified":True}
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/"runtime/hybrid-agent-state/instances"
   path.mkdir(parents=True)
   (path/"mc005.json").write_text("{}")
   with patch("hybrid_agent_worker._instance_runtime_module",return_value=SimpleNamespace(get_instance=lambda _:{})), \
        patch("minecraft_current_neoforge_collector.collect_current_neoforge_attestations",return_value=[claim]), \
        patch("minecraft_recovery_heartbeat_claims.owned_instance_ids_for_agent",return_value=set()), \
        patch("minecraft_current_neoforge_event_persistence.persist_current_neoforge_attestations") as persist:
    result=process_hybrid_current_neoforge_attestation_cycle(object(),Path(temp),"agent")
  self.assertEqual(result,{"status":"collected","verified":0})
  persist.assert_not_called()
if __name__=="__main__":unittest.main()
