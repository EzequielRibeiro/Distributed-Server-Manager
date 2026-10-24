#!/usr/bin/env python3
"""Isolated integration: present-state Agent proof -> authenticated audit -> Controller projection."""
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for part in ("agents/linux/runtime","dashboard","database"):
 sys.path.insert(0,str(ROOT/part))
from minecraft_current_neoforge_collector import collect_current_neoforge_attestations
from minecraft_current_neoforge_heartbeat_claims import current_attestations_from_heartbeat
from minecraft_current_neoforge_event_persistence import persist_current_neoforge_attestations
from minecraft_current_neoforge_assessment import assess_current_neoforge
from minecraft_recovery_customer_projection import visible_provision_after_recovery

class FullCurrentFlowTest(unittest.TestCase):
 def test_current_attestation_is_audited_but_does_not_erase_99_percent_history(self):
  with tempfile.TemporaryDirectory() as temp:
   record={"instance_id":"mc005","agent_id":"hybrid","runtime_id":"minecraft.java.neoforge",
           "working_directory":temp,
           "content_root":"/srv/capivara/game-data/minecraft/neoforge/26.1.2/26.1.2.94"}
   with patch("minecraft_current_neoforge_attestation.verify_installed_neoforge",
              return_value={"evidence":{"launch_args":"valid"}}):
    collected=collect_current_neoforge_attestations(
     ["mc005"],agent_id="hybrid",read_instance=lambda _:record,
     observed_at="2026-10-24T09:00:00Z")
   self.assertEqual(len(collected),1)
   accepted=current_attestations_from_heartbeat(
    {"minecraft_current_neoforge_attestations":collected},
    authenticated_agent_id="hybrid",owned_instance_ids={"mc005"})
   self.assertEqual(len(accepted),1)
   published=[]
   with patch("minecraft_current_neoforge_event_persistence.UniversalEventRepository") as events:
    events.return_value.publish.side_effect=lambda event:(published.append(event) or {"created":True})
    self.assertEqual(persist_current_neoforge_attestations(object(),accepted)["created"],1)
   self.assertEqual(published[0]["event_type"],"MINECRAFT_NEOFORGE_CURRENT_VERIFIED")
   failure={"status":"failed","instance_id":"mc005","agent_id":"hybrid",
            "completed_at":"2026-10-23T20:00:00Z","progress":99, "request":{"content":{"selection":{"loader_version":"26.1.2.94"}}}}
   health={"instance_id":"mc005","observed_state":"running","reconcile_status":"healthy",
           "health":"healthy","reported_at":"2026-10-24T10:00:00Z"}
   assessed=assess_current_neoforge(agent_id="hybrid",instance_id="mc005",
                                   failed_provision=failure,attestation_events=published,runtime_health=health)
   self.assertEqual(assessed["status"],"current_runtime_verified")
   visible=visible_provision_after_recovery(failure,{"status":"missing_recovery_evidence",
                                                     "current_neoforge":assessed})
   self.assertEqual(visible["progress"],99)
   self.assertEqual(visible["current_runtime_diagnosis"],
                    "running_verified_installation_history_unresolved")
   self.assertEqual(failure["status"],"failed")
if __name__=="__main__":unittest.main()
