from __future__ import annotations
import sys,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"database",ROOT/"dashboard",ROOT/"core"):
 if str(p) not in sys.path:sys.path.insert(0,str(p))
from agent_remote_http import dispatch_heartbeat


class AuthenticatedServerPackOfferTests(unittest.TestCase):
 def setUp(self):
  self.stack=ExitStack()
  self.addCleanup(self.stack.close)
  for name in (
   "_attach_uninstall_state","_attach_update_state","_attach_provisioning_state",
   "_attach_game_data_state","_attach_instance_state","_attach_doctor_state",
   "_reconcile_link_incident","_attach_backup_clone_state",
  ):
   self.stack.enter_context(patch("agent_remote_http."+name))
  auth=self.stack.enter_context(patch("agent_remote_http.AgentPairingRepository"))
  auth.return_value.authenticate.return_value={"agent_id":"trusted-agent","status":"active"}
  self.stack.enter_context(patch("agent_remote_http.record_agent_heartbeat",
       return_value={"agent_id":"trusted-agent","health_status":"online"}))
  self.stack.enter_context(patch("agent_remote_http.validated_heartbeat_recovery_claims",
       return_value=[]))
  self.stack.enter_context(patch("minecraft_recovery_heartbeat_claims.owned_instance_ids_for_agent",
       return_value=set()))
  self.lookup=self.stack.enter_context(patch("agent_remote_http.serverpack_recovery_offer"))
  self.headers={
   "X-Capivara-Agent-Credential":"test-credential",
   "X-Capivara-Agent-Secret":"test-secret",
   "X-Capivara-Agent-Fingerprint":"test-fingerprint",
  }
 def post(self,payload):
  return dispatch_heartbeat(payload,headers=self.headers,backend=object())

 def test_no_probe_keeps_existing_heartbeat_behavior(self):
  status,result=self.post({"agent_id":"untrusted-agent"})
  self.assertEqual(status,200)
  self.assertNotIn("serverpack_recovery_offer",result)
  self.lookup.assert_not_called()

 def test_probe_is_bound_to_authenticated_identity(self):
  self.lookup.return_value={"status":"verified","bundle_revision":8}
  status,result=self.post({"agent_id":"imposter",
     "serverpack_recovery_probe":{"provisioning_id":"instance-provision-abc",
       "instance_id":"mc005","candidate_sha256":"a"*64}})
  self.assertEqual(status,200)
  self.assertEqual(result["serverpack_recovery_offer"]["bundle_revision"],8)
  self.lookup.assert_called_once()
  self.assertEqual(self.lookup.call_args.kwargs["authenticated_agent_id"],"trusted-agent")

 def test_report_delivery_uses_authenticated_identity(self):
  payload={"serverpack_report_delivery":{"instance_id":"mc005","reports":[]}}
  with patch("agent_remote_http.dispatch_serverpack_report_delivery",
             return_value={"status":"disabled"}) as deliver:
   status,result=self.post({"agent_id":"fake-agent",**payload})
  self.assertEqual(status,200)
  self.assertEqual(result["serverpack_report_delivery"]["status"],"disabled")
  deliver.assert_called_once()
  self.assertEqual(deliver.call_args.kwargs["authenticated_agent_id"],"trusted-agent")

 def test_report_delivery_failure_isolated_from_heartbeat(self):
  with patch("agent_remote_http.dispatch_serverpack_report_delivery",
             side_effect=RuntimeError("database unavailable")):
   status,result=self.post({"serverpack_report_delivery":{"instance_id":"mc005"}})
  self.assertEqual(status,200)
  self.assertEqual(result["health_status"],"online")
  self.assertEqual(result["serverpack_report_delivery"]["status"],"unavailable")

 def test_receipt_query_failure_does_not_break_heartbeat(self):
  self.lookup.side_effect=RuntimeError("database unavailable")
  status,result=self.post({"serverpack_recovery_probe":{"instance_id":"mc005"}})
  self.assertEqual(status,200)
  self.assertEqual(result["serverpack_recovery_offer"],
   {"status":"unavailable","reason":"receipt_query_unavailable"})
  self.assertEqual(result["health_status"],"online")

if __name__=="__main__":unittest.main()
