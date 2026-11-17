from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"database",ROOT/"core",ROOT/"tests"):
 if str(p) not in sys.path:sys.path.insert(0,str(p))
from minecraft_serverpack_pending_publication_atomic_test import AtomicPendingPublicationTest
from minecraft_serverpack_agent_report_publication import (
 publish_attested_serverpack_reports,ServerPackAgentReportPublicationError)


class ServerPackAgentReportTests(unittest.TestCase):
 def setUp(self):
  self.fixture=AtomicPendingPublicationTest(
   methodName="test_completed_agent_result_publishes_bundle_in_same_completion_transaction")
  self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
  self.pending=self.fixture.pending()
  self.repo,self.operation=self.fixture.enqueue(self.pending)
  self.agent="pr839-isolated-agent";self.iid="pr855-controller-atomic"
  self.kwargs=dict(
   backend=self.fixture.backend,provisioning_id=self.operation["provisioning_id"],
   agent_id=self.agent,instance_id=self.iid,
   candidate_sha256=self.pending["candidate_sha256"])
  self.repo.apply_result(self.agent,self.fixture.completed(self.operation,self.pending))
  self.reports=self.build_reports()
 def build_reports(self):
  with self.fixture.backend.connect() as db:
   rows=db.execute("SELECT * FROM content_assignments WHERE instance_id=?",(self.iid,)).fetchall()
  return [dict(
   agent_id=self.agent,instance_id=self.iid,content_id=row["content_id"],
   status="applied",desired_state=row["desired_state"],desired_revision=row["revision"],
   applied_revision=row["revision"],desired_checksum=row["checksum"],
   applied_checksum=row["checksum"],
   installed_version=row["version"] if row["desired_state"]=="installed" else None,
   security_state="clean" if row["desired_state"]=="installed" else "unscanned",
   attestation_candidate_sha256=self.pending["candidate_sha256"],
   last_error=None,
  ) for row in rows]
 def publish(self):return publish_attested_serverpack_reports(**self.kwargs,reports=self.reports)
 def report_count(self):
  with self.fixture.backend.connect() as db:
   return db.execute("SELECT COUNT(*) AS n FROM agent_content_state WHERE instance_id=?",(self.iid,)).fetchone()["n"]

 def test_success_atomically_reports_all_members(self):
  result=self.publish()
  self.assertEqual(result["status"],"published")
  self.assertEqual(result["reports"],2)
  self.assertEqual(self.report_count(),2)

 def test_retry_is_idempotent(self):
  self.assertEqual(self.publish()["reports"],2)
  self.assertEqual(self.publish()["reports"],2)
  self.assertEqual(self.report_count(),2)

 def test_rejects_partial_batch_without_writes(self):
  self.reports.pop()
  with self.assertRaisesRegex(ServerPackAgentReportPublicationError,"partial"):
   self.publish()
  self.assertEqual(self.report_count(),0)

 def test_rejects_stale_child_revision_without_writes(self):
  self.reports[1]["applied_revision"]=0
  with self.assertRaisesRegex(ServerPackAgentReportPublicationError,"report revision"):
   self.publish()
  self.assertEqual(self.report_count(),0)

 def test_rejects_missing_scan(self):
  self.reports[1]["security_state"]="unscanned"
  with self.assertRaisesRegex(ServerPackAgentReportPublicationError,"report revision"):
   self.publish()
  self.assertEqual(self.report_count(),0)

 def test_rejects_different_candidate_attestation(self):
  self.reports[0]["attestation_candidate_sha256"]="0"*64
  with self.assertRaisesRegex(ServerPackAgentReportPublicationError,"candidate-bound"):
   self.publish()
  self.assertEqual(self.report_count(),0)

 def test_rejects_duplicate_report(self):
  self.reports[1]=dict(self.reports[0])
  with self.assertRaisesRegex(ServerPackAgentReportPublicationError,"duplicate"):
   self.publish()
  self.assertEqual(self.report_count(),0)

 def test_rejects_controller_revision_changed(self):
  with self.fixture.backend.transaction() as db:
   db.execute("UPDATE content_bundles SET revision=42 WHERE instance_id=?",(self.iid,))
  with self.assertRaisesRegex(Exception,"bundle"):
   self.publish()
  self.assertEqual(self.report_count(),0)

 def test_rejects_foreign_agent(self):
  self.reports[0]["agent_id"]="other"
  with self.assertRaisesRegex(ServerPackAgentReportPublicationError,"report revision"):
   self.publish()
  self.assertEqual(self.report_count(),0)

if __name__=="__main__":unittest.main()
