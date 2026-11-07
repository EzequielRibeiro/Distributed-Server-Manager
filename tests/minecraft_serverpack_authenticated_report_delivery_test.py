from __future__ import annotations
import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"database",ROOT/"dashboard",ROOT/"core",ROOT/"tests"):
 if str(p) not in sys.path:sys.path.insert(0,str(p))
from minecraft_serverpack_pending_publication_atomic_test import AtomicPendingPublicationTest
from minecraft_serverpack_authenticated_report_delivery import dispatch_serverpack_report_delivery


class ReportDeliveryTest(unittest.TestCase):
 def setUp(self):
  fixture=AtomicPendingPublicationTest(
   methodName="test_completed_agent_result_publishes_bundle_in_same_completion_transaction")
  self.fixture=fixture;fixture.setUp();self.addCleanup(fixture.tearDown)
  self.pending=fixture.pending();self.repo,self.op=fixture.enqueue(self.pending)
  self.agent="pr839-isolated-agent";self.instance="pr855-controller-atomic"
  self.repo.apply_result(self.agent,fixture.completed(self.op,self.pending))
  with fixture.backend.connect() as db:
   assignments=db.execute("SELECT * FROM content_assignments WHERE instance_id=?",(self.instance,)).fetchall()
  reports=[]
  for row in assignments:
   active=row["desired_state"]=="installed"
   reports.append(dict(
    agent_id=self.agent,instance_id=self.instance,content_id=row["content_id"],
    status="applied",desired_state=row["desired_state"],
    desired_revision=row["revision"],applied_revision=row["revision"],
    desired_checksum=row["checksum"],applied_checksum=row["checksum"],
    installed_version=row["version"] if active else None,
    security_state="clean" if active else "unscanned",
    attestation_candidate_sha256=self.pending["candidate_sha256"],last_error=None,
   ))
  self.payload=dict(provisioning_id=self.op["provisioning_id"],
   instance_id=self.instance,candidate_sha256=self.pending["candidate_sha256"],
   reports=reports)
 def deliver(self,**args):
  return dispatch_serverpack_report_delivery(self.fixture.backend,self.payload,
    authenticated_agent_id=args.get("agent",self.agent))
 def count(self):
  with self.fixture.backend.connect() as db:
   return db.execute("SELECT COUNT(*) n FROM agent_content_state WHERE instance_id=?",(self.instance,)).fetchone()["n"]
 def test_disabled_by_default(self):
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"0"}):
   self.assertEqual(self.deliver()["status"],"disabled")
   self.assertEqual(self.count(),0)
 def test_authorized_full_batch_and_retry(self):
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   self.assertEqual(self.deliver()["status"],"published")
   self.assertEqual(self.deliver()["reports"],2)
   self.assertEqual(self.count(),2)
 def test_foreign_agent_rejected_without_writes(self):
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   self.assertEqual(self.deliver(agent="imposter")["status"],"rejected")
   self.assertEqual(self.count(),0)
 def test_partial_batch_rejected_atomically(self):
  self.payload["reports"].pop()
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   self.assertEqual(self.deliver()["status"],"rejected")
   self.assertEqual(self.count(),0)
 def test_unknown_field_rejected(self):
  self.payload["surprise"]="secret"
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   self.assertEqual(self.deliver()["reason"],"invalid_batch")
   self.assertEqual(self.count(),0)
 def test_mismatched_candidate_rejected(self):
  self.payload["candidate_sha256"]="f"*64
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   self.assertEqual(self.deliver()["status"],"rejected")
   self.assertEqual(self.count(),0)
 def test_stale_version_rejected(self):
  self.payload["reports"][0]["installed_version"]="old"
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   self.assertEqual(self.deliver()["status"],"rejected")
   self.assertEqual(self.count(),0)
 def test_missing_scan_rejected(self):
  self.payload["reports"][0]["security_state"]="unscanned"
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   self.assertEqual(self.deliver()["status"],"rejected")
   self.assertEqual(self.count(),0)
 def test_duplicate_content_rejected(self):
  self.payload["reports"][1]=dict(self.payload["reports"][0])
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   self.assertEqual(self.deliver()["reason"],"invalid_report")
 def test_malformed_payload_rejected(self):
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   for payload in (None,[],{},{"reports":[]},dict(self.payload,reports=[1])):
    self.assertEqual(dispatch_serverpack_report_delivery(self.fixture.backend,payload,authenticated_agent_id=self.agent)["status"],"rejected")
 def test_heartbeat_authenticated_identity_not_body(self):
  with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}):
   self.payload["agent_id"]=self.agent
   self.assertEqual(self.deliver(agent="other")["status"],"rejected")
   self.assertEqual(self.count(),0)


if __name__=="__main__":unittest.main()
