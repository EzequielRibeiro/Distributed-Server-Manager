from __future__ import annotations
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for d in (ROOT,ROOT/"core",ROOT/"agents/common"):sys.path.insert(0,str(d))
from minecraft_serverpack_recovery_heartbeat_contract import (
 build_recovery_probe,verify_recovery_offer,ServerPackHeartbeatContractError)


class AgentRecoveryHeartbeatTests(unittest.TestCase):
 def setUp(self):
  self.provision="instance-provision-abc123"
  self.pending={"instance_id":"mc005","candidate_sha256":"a"*64,
   "migration_plan_sha256":"b"*64,
   "expected_previous_revision":7,
   "bundle":{"loader_version":"26.1.2.126"},
   "children":[{}]}
  self.result={"status":"completed","instance_id":"mc005",
   "provisioning_id":self.provision}
  self.journal={"phase":"committed","migration_plan_sha256":"b"*64,
   "target_loader_version":"26.1.2.126"}
  self.proof={**self.pending}
  self.offer={"kind":"ServerPackRecoveryOffer","status":"verified",
   "provisioning_id":self.provision,"instance_id":"mc005",
   "candidate_sha256":"a"*64,"bundle_revision":8,
   "manifest_sha256":"d"*64,"loader_version":"26.1.2.126",
   "child_count":1,"instruction":"verify_local_sources_before_recovery"}
 def request(self):
  with patch("minecraft_serverpack_recovery_heartbeat_contract.authorize_after_agent_completion",
             return_value=self.proof):
   return build_recovery_probe(provisioning_id=self.provision,pending=self.pending,
    agent_result=self.result,committed_journal=self.journal)
 def test_roundtrip_and_replay(self):
  probe=self.request()
  self.assertEqual(probe,self.request())
  validated=verify_recovery_offer(probe,self.offer,self.pending)
  self.assertEqual(validated["bundle_revision"],8)
  self.assertEqual(validated["status"],"verified")
 def test_uncommitted_journal_rejected(self):
  self.journal["phase"]="swapped"
  with self.assertRaisesRegex(ServerPackHeartbeatContractError,"not committed"):self.request()
 def test_migration_fingerprint_rejected(self):
  self.journal["migration_plan_sha256"]="f"*64
  with self.assertRaisesRegex(ServerPackHeartbeatContractError,"not committed"):self.request()
 def test_wrong_provision_rejected(self):
  self.result["provisioning_id"]="instance-provision-other"
  with self.assertRaisesRegex(ServerPackHeartbeatContractError,"another provisioning"):self.request()
 def test_foreign_result_rejected(self):
  self.result["instance_id"]="other"
  with self.assertRaisesRegex(ServerPackHeartbeatContractError,"another instance"):self.request()
 def test_wrong_candidate_offer_rejected(self):
  self.offer["candidate_sha256"]="f"*64
  with self.assertRaisesRegex(ServerPackHeartbeatContractError,"mismatches"):verify_recovery_offer(self.request(),self.offer,self.pending)
 def test_wrong_revision_offer_rejected(self):
  self.offer["bundle_revision"]=9
  with self.assertRaisesRegex(ServerPackHeartbeatContractError,"mismatches"):verify_recovery_offer(self.request(),self.offer,self.pending)
 def test_missing_manifest_checksum_rejected(self):
  self.offer["manifest_sha256"]="foo"
  with self.assertRaisesRegex(ServerPackHeartbeatContractError,"checksum"):verify_recovery_offer(self.request(),self.offer,self.pending)
 def test_wrong_loader_offer_rejected(self):
  self.offer["loader_version"]="26.1.2.999"
  with self.assertRaisesRegex(ServerPackHeartbeatContractError,"mismatches"):verify_recovery_offer(self.request(),self.offer,self.pending)
 def test_no_agent_completion_proof_rejected(self):
  with patch("minecraft_serverpack_recovery_heartbeat_contract.authorize_after_agent_completion",
   side_effect=ValueError("mismatch")):
   with self.assertRaisesRegex(ServerPackHeartbeatContractError,"no verified commit"):
    build_recovery_probe(provisioning_id=self.provision,pending=self.pending,
     agent_result=self.result,committed_journal=self.journal)


if __name__=="__main__":unittest.main()
