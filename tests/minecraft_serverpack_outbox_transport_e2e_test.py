from __future__ import annotations
import os,sys,tempfile,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"database",ROOT/"dashboard",ROOT/"core",
          ROOT/"agents/common",ROOT/"agents/linux/runtime",ROOT/"tests"):
 if str(p) not in sys.path:sys.path.insert(0,str(p))
from minecraft_serverpack_authenticated_report_delivery_test import ReportDeliveryTest
from minecraft_serverpack_report_outbox import (
 queue_serverpack_report_delivery, read_serverpack_report_delivery,
 acknowledge_serverpack_report_delivery,
)
from agent_remote_http import dispatch_heartbeat


class ServerPackOutboxTransportE2E(unittest.TestCase):
 def setUp(self):
  fixture=ReportDeliveryTest(methodName="test_disabled_by_default")
  fixture.setUp();self.addCleanup(fixture.tearDown)
  self.fixture=fixture
  self.stack=ExitStack();self.addCleanup(self.stack.close)
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
  self.directory=Path(temp.name)
  evidence={}
  for key in ("source_promotion_journal","state_promotion_journal",
              "staged_manifest","prepared_reports","active_states","active_snapshot"):
   p=self.directory/(key+".json");p.write_text("{}")
   evidence[key]=p
  self.proof={
   "kind":"VerifiedServerPackRecoveryOffer","status":"verified",
   "provisioning_id":fixture.op["provisioning_id"],
   "instance_id":fixture.instance,"candidate_sha256":fixture.pending["candidate_sha256"],
   "bundle_revision":2,
  }
  self.stack.enter_context(patch("minecraft_serverpack_report_outbox.build_committed_serverpack_report_delivery",
   return_value=fixture.payload))
  self.assertEqual(queue_serverpack_report_delivery(state_dir=self.directory,
   offer=self.proof,agent_id=fixture.agent,**evidence),"queued")
  for name in (
   "_attach_uninstall_state","_attach_update_state","_attach_provisioning_state",
   "_attach_game_data_state","_attach_instance_state","_attach_doctor_state",
   "_reconcile_link_incident","_attach_backup_clone_state",
  ):
   self.stack.enter_context(patch("agent_remote_http."+name))
  auth=self.stack.enter_context(patch("agent_remote_http.AgentPairingRepository"))
  auth.return_value.authenticate.return_value={"agent_id":fixture.agent,"status":"active"}
  self.stack.enter_context(patch("agent_remote_http.record_agent_heartbeat",
       return_value={"agent_id":fixture.agent,"health_status":"online"}))
  self.stack.enter_context(patch("agent_remote_http.validated_heartbeat_recovery_claims",
       return_value=[]))
  self.stack.enter_context(patch("minecraft_recovery_heartbeat_claims.owned_instance_ids_for_agent",
       return_value=set()))
  self.headers={"X-Capivara-Agent-Credential":"test","X-Capivara-Agent-Secret":"test",
                "X-Capivara-Agent-Fingerprint":"test"}
  self.stack.enter_context(patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}))
 def roundtrip(self,authenticated_agent=None):
  queued=read_serverpack_report_delivery(self.directory)
  self.assertIsNotNone(queued)
  payload,filename=queued
  if authenticated_agent is not None:
   from agent_remote_http import AgentPairingRepository
   AgentPairingRepository.return_value.authenticate.return_value={
    "agent_id":authenticated_agent,"status":"active"}
  status,result=dispatch_heartbeat({"serverpack_report_delivery":payload},
   headers=self.headers,backend=self.fixture.fixture.backend)
  self.assertEqual(status,200)
  response=result.get("serverpack_report_delivery") or {}
  return (payload,filename,response)
 def test_delivery_commit_ack_and_outbox_retirement(self):
  payload,filename,reply=self.roundtrip()
  self.assertEqual(reply["status"],"published")
  self.assertEqual(self.fixture.count(),2)
  self.assertTrue(acknowledge_serverpack_report_delivery(
    self.directory,filename,payload,reply))
  self.assertIsNone(read_serverpack_report_delivery(self.directory))
 def test_lost_network_response_retries_after_controller_commit(self):
  payload,filename,first=self.roundtrip()
  self.assertEqual(first["status"],"published")
  self.assertEqual(self.fixture.count(),2)
  # HTTP connection disappears after SQL commit; response never reaches Agent.
  self.assertIsNotNone(read_serverpack_report_delivery(self.directory))
  payload2,filename2,again=self.roundtrip()
  self.assertEqual(payload2,payload)
  self.assertEqual(filename2,filename)
  self.assertEqual(again["status"],"published")
  self.assertEqual(self.fixture.count(),2)
  self.assertTrue(acknowledge_serverpack_report_delivery(
   self.directory,filename2,payload2,again))
 def test_foreign_authenticated_agent_keeps_outbox(self):
  with patch("agent_remote_http.AgentPairingRepository") as auth:
   auth.return_value.authenticate.return_value={"agent_id":"foreign-agent","status":"active"}
   payload,filename,response=self.roundtrip()
  self.assertEqual(response["status"],"rejected")
  self.assertEqual(self.fixture.count(),0)
  self.assertFalse(acknowledge_serverpack_report_delivery(
   self.directory,filename,payload,response))
  self.assertIsNotNone(read_serverpack_report_delivery(self.directory))
 def test_disabled_delivery_retains_pending(self):
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"0"}):
   payload,filename,response=self.roundtrip()
  self.assertEqual(response["status"],"disabled")
  self.assertEqual(self.fixture.count(),0)
  self.assertFalse(acknowledge_serverpack_report_delivery(
   self.directory,filename,payload,response))
 def test_controller_rejects_tampered_batch_and_preserves_pending(self):
  original=read_serverpack_report_delivery(self.directory)
  bad=dict(original[0])
  bad["reports"]=bad["reports"][:-1]
  status,result=dispatch_heartbeat({"serverpack_report_delivery":bad},
   headers=self.headers,backend=self.fixture.fixture.backend)
  self.assertEqual(status,200)
  self.assertEqual(result["serverpack_report_delivery"]["status"],"rejected")
  self.assertEqual(self.fixture.count(),0)
  self.assertIsNotNone(read_serverpack_report_delivery(self.directory))


if __name__=="__main__":unittest.main()
