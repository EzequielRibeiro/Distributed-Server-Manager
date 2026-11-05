import importlib.util
from contextlib import contextmanager
from pathlib import Path
import json
import tempfile
import unittest

P=Path(__file__).resolve().parents[1]/"agents/linux/runtime/minecraft_serverpack_finalization_scheduler.py"
spec=importlib.util.spec_from_file_location("scheduler",P)
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
PLAN="a"*64
OUTER={"agent_id":"agent-test","instance_id":"instance-test","operation":"minecraft_serverpack_migration","status":"finalization_pending","migration_plan_sha256":PLAN}
RESULT={"instance_id":"instance-test","provisioning_id":"provision-test","status":"running","current_step":"minecraft_serverpack_finalization","finalization_state":"pending","minecraft_serverpack_migration":{"status":"finalization_pending","migration_plan_sha256":PLAN}}


class SchedulerTest(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.root=Path(self.t.name)
  (self.root/"instance-provisioning").mkdir()
  self.result=self.root/"instance-provisioning/provision-test.result.json"
  self.result.write_text(json.dumps(RESULT))
  self.events=[]
  @contextmanager
  def lock(instance):
   self.events.append("lock:"+instance)
   try: yield
   finally:self.events.append("unlock:"+instance)
  self.lock=lock
  self.op=dict(OUTER)
 def run_scan(self,**kwargs):
  return s.scan_pending_finalizations(state_root=self.root,agent_id="agent-test",lock_instance=self.lock,read_operation=lambda _:self.op,**kwargs)
 def test_default_readonly(self):
  x=self.run_scan()
  self.assertEqual(x[0]["status"],"pending")
  self.assertEqual(self.events,["lock:instance-test","unlock:instance-test"])
 def test_dispatch_disabled_even_with_callback(self):
  self.run_scan(dispatch=lambda *_:self.events.append("dispatch"))
  self.assertNotIn("dispatch",self.events)
 def test_dispatch_holds_lock(self):
  self.run_scan(enabled=True,dispatch=lambda *_:self.events.append("dispatch"))
  self.assertEqual(self.events,["lock:instance-test","dispatch","unlock:instance-test"])
 def test_wrong_agent_rejected(self):
  self.op["agent_id"]="foreign"
  self.assertEqual(self.run_scan()[0]["reason"],"operation_mismatch")
 def test_plan_mismatch_rejected(self):
  self.op["migration_plan_sha256"]="b"*64
  self.assertEqual(self.run_scan()[0]["reason"],"plan_mismatch")
 def test_changed_result_rejected(self):
  @contextmanager
  def lock(_):
   self.result.write_text(json.dumps({**RESULT,"finalization_state":"other"}))
   yield
  self.lock=lock
  self.assertEqual(self.run_scan()[0]["reason"],"result_changed")
 def test_completed_without_evidence_ignored(self):
  self.result.write_text(json.dumps({**RESULT,"status":"completed"}))
  self.assertEqual(self.run_scan(),[])
 def test_completed_with_evidence_requires_journal_reconciliation(self):
  detail={**RESULT["minecraft_serverpack_migration"],"status":"completed",
          "trace":["committed","finalized"],"finalization":{"status":"archived"}}
  self.result.write_text(json.dumps({**RESULT,"status":"completed",
                                      "minecraft_serverpack_migration":detail}))
  self.assertEqual(self.run_scan()[0]["status"],"pending_journal_reconciliation")
 def test_completed_with_evidence_dispatch_holds_lock(self):
  detail={**RESULT["minecraft_serverpack_migration"],"status":"completed",
          "trace":["committed","finalized"],"finalization":{"status":"archived"}}
  self.result.write_text(json.dumps({**RESULT,"status":"completed",
                                      "minecraft_serverpack_migration":detail}))
  self.assertEqual(self.run_scan(enabled=True,dispatch=lambda *_:self.events.append("dispatch"))[0]["status"],"dispatched")
  self.assertEqual(self.events,["lock:instance-test","dispatch","unlock:instance-test"])
 def test_completed_with_invalid_archive_denied(self):
  detail={**RESULT["minecraft_serverpack_migration"],"status":"completed",
          "trace":["committed","finalized"],"finalization":{"status":"missing"}}
  self.result.write_text(json.dumps({**RESULT,"status":"completed",
                                      "minecraft_serverpack_migration":detail}))
  self.assertEqual(self.run_scan()[0]["reason"],"plan_mismatch")
 def test_unsafe_link_rejected(self):
  self.result.unlink()
  target=self.root/"target";target.write_text(json.dumps(RESULT))
  self.result.symlink_to(target)
  self.assertEqual(self.run_scan()[0]["reason"],"unsafe_result_path")
 def test_wrong_filename_rejected(self):
  self.result.write_text(json.dumps({**RESULT,"provisioning_id":"other"}))
  self.assertEqual(self.run_scan()[0]["reason"],"invalid_identity")
 def test_missing_root(self):
  self.result.unlink();(self.root/"instance-provisioning").rmdir()
  self.assertEqual(self.run_scan(),[])
 def test_older_completed_results_do_not_starve_pending(self):
  for i in range(6):
   (self.root/"instance-provisioning"/f"a{i}.result.json").write_text(
    json.dumps({**RESULT,"provisioning_id":f"a{i}","status":"completed"}))
  self.assertEqual(self.run_scan(max_candidates=1)[0]["status"],"pending")
 def test_target_instance_skips_foreign_pending(self):
  other={**RESULT,"instance_id":"foreign","provisioning_id":"aaa"}
  (self.root/"instance-provisioning/aaa.result.json").write_text(json.dumps(other))
  scanned=s.scan_pending_finalizations(
   state_root=self.root,agent_id="agent-test",lock_instance=self.lock,
   read_operation=lambda _:self.op,max_candidates=1,target_instance_id="instance-test")
  self.assertEqual(scanned[0]["instance_id"],"instance-test")
  self.assertEqual(self.events,["lock:instance-test","unlock:instance-test"])
 def test_target_only_after_many_foreign_records(self):
  for i in range(275):
   (self.root/"instance-provisioning"/f"a{i:04}.result.json").write_text(
    json.dumps({**RESULT,"instance_id":"foreign","provisioning_id":f"a{i:04}"}))
  scanned=s.scan_pending_finalizations(
   state_root=self.root,agent_id="agent-test",lock_instance=self.lock,
   read_operation=lambda _:self.op,max_candidates=1,target_instance_id="instance-test")
  self.assertEqual(scanned[0]["status"],"pending")
 def test_target_token_validation(self):
  with self.assertRaises(s.FinalizationSchedulerError):
   s.scan_pending_finalizations(state_root=self.root,agent_id="agent-test",lock_instance=self.lock,
    read_operation=lambda _:self.op,target_instance_id="../../foreign")
 def test_bounded_scan(self):
  with self.assertRaises(s.FinalizationSchedulerError):
   self.run_scan(max_candidates=0)
 def test_unreadable_json_rejected(self):
  self.result.write_text("{bad")
  self.assertEqual(self.run_scan()[0]["reason"],"unreadable_result")

if __name__=="__main__":unittest.main()
