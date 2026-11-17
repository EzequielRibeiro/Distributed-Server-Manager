import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/common"))
from minecraft_serverpack_recovery_coordinator import resume_serverpack_recovery,ServerPackRecoveryCoordinatorError

class CoordinatorTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
  self.path=Path(temp.name)/"journal.json";self.sha="c"*64;self.calls=[]
  self.receipt=lambda:{"kind":"VerifiedServerPackControllerReceipt","status":"verified",
   "instance_id":"mc005","candidate_sha256":self.sha,"bundle_revision":8}
  self.steps={}
  for name in ("prepare_sources_and_states","promote_sources",
               "promote_local_states_and_snapshot","publish_attested_reports","verify_ack"):
   def fn(n=name):
    self.calls.append(n)
    if n=="verify_ack":return {"kind":"VerifiedServerPackContentConvergence",
      "status":"ready","instance_id":"mc005","candidate_sha256":self.sha,"bundle_revision":8}
    return {"status":"committed"}
   self.steps[name]=fn
 def execute(self,**kwargs):
  return resume_serverpack_recovery(journal_path=self.path,instance_id="mc005",
   candidate_sha256=self.sha,revision=8,receipt_check=self.receipt,callbacks=self.steps,**kwargs)
 def test_success_and_repeat(self):
  self.assertEqual(self.execute()["status"],"completed")
  self.assertTrue(self.execute()["replayed"]);self.assertEqual(len(self.calls),5)
 def test_checkpoint_crash_restarts_at_next_phase(self):
  def crash(phase):
   if phase=="sources_promoted":raise SystemExit()
  with self.assertRaises(SystemExit):self.execute(after_phase=crash)
  self.assertEqual(self.execute()["status"],"completed")
  self.assertEqual(self.calls.count("promote_sources"),1)
 def test_crash_before_checkpoint_repeats_idempotent_callback(self):
  old=self.steps["promote_sources"]
  def failed_once():
   self.steps["promote_sources"]=old;old();raise SystemExit()
  self.steps["promote_sources"]=failed_once
  with self.assertRaises(SystemExit):self.execute()
  self.execute();self.assertEqual(self.calls.count("promote_sources"),2)
 def test_invalid_receipt_blocks_all(self):
  self.receipt=lambda:{"status":"failed"}
  with self.assertRaisesRegex(ServerPackRecoveryCoordinatorError,"Controller receipt"):
   self.execute()
  self.assertEqual(self.calls,[])
 def test_bad_ack_never_marks_complete(self):
  self.steps["verify_ack"]=lambda:{"status":"pending"}
  with self.assertRaisesRegex(ServerPackRecoveryCoordinatorError,"ACK"):
   self.execute()
  self.assertEqual(json.loads(self.path.read_text())["phase"],"reports_published")
 def test_foreign_journal_rejected(self):
  self.execute()
  with self.assertRaisesRegex(ServerPackRecoveryCoordinatorError,"foreign journal"):
   resume_serverpack_recovery(journal_path=self.path,instance_id="mc005",
    candidate_sha256="d"*64,revision=8,receipt_check=self.receipt,callbacks=self.steps)
 def test_corrupt_journal_rejected(self):
  self.path.write_text("{bad")
  with self.assertRaisesRegex(ServerPackRecoveryCoordinatorError,"corrupt"):
   self.execute()
 def test_incomplete_phase_rejected(self):
  self.steps["prepare_sources_and_states"]=lambda:{"status":"failed"}
  with self.assertRaisesRegex(ServerPackRecoveryCoordinatorError,"phase failed"):
   self.execute()
  self.assertEqual(json.loads(self.path.read_text())["phase"],"awaiting_sources")
 def test_missing_callbacks_rejected(self):
  self.steps.pop("promote_sources")
  with self.assertRaisesRegex(ServerPackRecoveryCoordinatorError,"missing recovery"):
   self.execute()
if __name__=="__main__":unittest.main()
