from __future__ import annotations
import sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"database",ROOT/"dashboard",ROOT/"core",ROOT/"tests"):
 if str(p) not in sys.path:sys.path.insert(0,str(p))
from minecraft_serverpack_pending_publication_atomic_test import AtomicPendingPublicationTest
from minecraft_serverpack_heartbeat_recovery_offer import serverpack_recovery_offer


class RecoveryOfferTests(unittest.TestCase):
 def setUp(self):
  f=AtomicPendingPublicationTest(methodName="test_completed_agent_result_publishes_bundle_in_same_completion_transaction")
  self.fixture=f;f.setUp();self.addCleanup(f.tearDown)
  self.pending=f.pending()
  self.repo,self.op=f.enqueue(self.pending)
  self.body={"serverpack_recovery_probe":{
   "provisioning_id":self.op["provisioning_id"],
   "instance_id":"pr855-controller-atomic",
   "candidate_sha256":self.pending["candidate_sha256"]}}
 def call(self,agent="pr839-isolated-agent",body=None):
  return serverpack_recovery_offer(self.fixture.backend,
   self.body if body is None else body,authenticated_agent_id=agent)
 def done(self):
  self.repo.apply_result("pr839-isolated-agent",
   self.fixture.completed(self.op,self.pending))
 def test_no_probe_is_noop(self):
  self.assertIsNone(self.call(body={}))
 def test_before_committed_receipt_rejects(self):
  self.assertEqual(self.call()["status"],"rejected")
 def test_completed_receipt_bound_to_agent(self):
  self.done()
  offer=self.call()
  self.assertEqual(offer["status"],"verified")
  self.assertEqual(offer["bundle_revision"],2)
  self.assertEqual(offer["child_count"],1)
  self.assertEqual(offer["instruction"],"verify_local_sources_before_recovery")
  self.assertEqual(offer,self.call())
 def test_agent_impersonation_fails(self):
  self.done()
  self.assertEqual(self.call(agent="other-agent")["reason"],"receipt_not_verified")
 def test_body_identity_does_not_override_authentication(self):
  self.done()
  self.body["agent_id"]="pr839-isolated-agent"
  self.assertEqual(self.call(agent="other-agent")["reason"],"receipt_not_verified")
 def test_stale_sha_fails(self):
  self.done()
  self.body["serverpack_recovery_probe"]["candidate_sha256"]="f"*64
  self.assertEqual(self.call()["reason"],"receipt_not_verified")
 def test_malformed_input_fails_bounded(self):
  for bad in ([],None,{},{"candidate_sha256":"f"*64}, {"provisioning_id":"../../etc/passwd"},
             {**self.body["serverpack_recovery_probe"],"secret":"no"}):
   self.assertEqual(self.call(body={"serverpack_recovery_probe":bad})["reason"],"invalid_probe")
 def test_controller_query_error_is_fail_closed(self):
  with patch("minecraft_serverpack_heartbeat_recovery_offer.confirmed_serverpack_receipt",
             side_effect=RuntimeError("db temporarily unavailable")):
   with self.assertRaisesRegex(RuntimeError,"temporarily unavailable"):
    self.call()

 def test_no_db_lookup_for_invalid_sha(self):
  with patch("minecraft_serverpack_heartbeat_recovery_offer.confirmed_serverpack_receipt") as verify:
   self.body["serverpack_recovery_probe"]["candidate_sha256"]="../bad"
   self.assertEqual(self.call()["status"],"rejected")
   verify.assert_not_called()


if __name__=="__main__":unittest.main()
