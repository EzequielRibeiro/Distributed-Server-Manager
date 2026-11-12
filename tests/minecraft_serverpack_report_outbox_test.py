from __future__ import annotations
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"agents/common",ROOT/"agents/linux/runtime"):sys.path.insert(0,str(p))
from minecraft_serverpack_report_outbox import (
 queue_serverpack_report_delivery,read_serverpack_report_delivery,
 acknowledge_serverpack_report_delivery,
)


class OutboxTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.iid="mc005";self.pid="instance-provision-abc"
  self.offer=dict(kind="VerifiedServerPackRecoveryOffer",status="verified",
   provisioning_id=self.pid,instance_id=self.iid,
   candidate_sha256="a"*64,bundle_revision=8)
  self.paths={}
  for name in ("source_promotion_journal","state_promotion_journal",
   "staged_manifest","prepared_reports","active_states","active_snapshot"):
   p=self.root/(name+".json")
   p.write_text('{}')
   self.paths[name]=p
  self.data=dict(provisioning_id=self.pid,instance_id=self.iid,
   candidate_sha256="a"*64,reports=[{"content_id":"pack"}])
  self.confirm=dict(status="published",provisioning_id=self.pid,
   instance_id=self.iid,candidate_sha256="a"*64,bundle_revision=8,reports=1)
  self.patch=patch("minecraft_serverpack_report_outbox.build_committed_serverpack_report_delivery",
   return_value=self.data)
  self.verifier=self.patch.start()
  self.addCleanup(self.patch.stop)
 def queue(self):
  return queue_serverpack_report_delivery(state_dir=self.root,offer=self.offer,
   agent_id="agent",**self.paths)
 def test_queue_read_ack(self):
  self.assertEqual(self.queue(),"queued")
  data,filename=read_serverpack_report_delivery(self.root)
  self.assertEqual(data,self.data)
  self.assertTrue(acknowledge_serverpack_report_delivery(self.root,filename,data,self.confirm))
  self.assertIsNone(read_serverpack_report_delivery(self.root))
 def test_idempotent_enqueue(self):
  self.assertEqual(self.queue(),"queued")
  self.assertEqual(self.queue(),"already_queued")
 def test_no_ack_on_failure_keeps_retry(self):
  self.queue()
  self.assertFalse(acknowledge_serverpack_report_delivery(
   self.root,self.pid+".json",self.data,dict(self.confirm,status="unavailable")))
  self.assertIsNotNone(read_serverpack_report_delivery(self.root))
 def test_no_ack_on_wrong_sha(self):
  self.queue()
  self.assertFalse(acknowledge_serverpack_report_delivery(
   self.root,self.pid+".json",self.data,dict(self.confirm,candidate_sha256="f"*64)))
  self.assertIsNotNone(read_serverpack_report_delivery(self.root))
 def test_no_ack_on_wrong_revision(self):
  self.queue()
  self.assertFalse(acknowledge_serverpack_report_delivery(
   self.root,self.pid+".json",self.data,dict(self.confirm,bundle_revision=9)))
  self.assertIsNotNone(read_serverpack_report_delivery(self.root))
 def test_conflicting_queue_rejected(self):
  self.queue()
  self.offer["candidate_sha256"]="f"*64
  with self.assertRaisesRegex(ValueError,"conflicting"):self.queue()
 def test_symlinked_outbox_ignored(self):
  self.queue()
  file=self.root/"serverpack-report-outbox"/(self.pid+".json")
  other=self.root/"other.json";file.rename(other)
  file.symlink_to(other)
  self.assertIsNone(read_serverpack_report_delivery(self.root))
 def test_revalidate_each_delivery(self):
  self.queue()
  self.assertEqual(read_serverpack_report_delivery(self.root)[0],self.data)
  self.assertEqual(read_serverpack_report_delivery(self.root)[0],self.data)
  self.assertEqual(self.verifier.call_count,3)
 def test_outbox_defaults_empty(self):
  self.assertIsNone(read_serverpack_report_delivery(self.root))
 def test_malformed_ack_does_not_remove(self):
  self.queue()
  self.assertFalse(acknowledge_serverpack_report_delivery(
   self.root,self.pid+".json",self.data,{"status":"published"}))
  self.assertIsNotNone(read_serverpack_report_delivery(self.root))


if __name__=="__main__":unittest.main()
