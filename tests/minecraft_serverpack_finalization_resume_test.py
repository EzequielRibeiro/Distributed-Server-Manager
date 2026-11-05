"""Crash replay across active journal, archival and restart boundaries."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/"agents/linux/runtime"))
from minecraft_serverpack_finalization_resume import resume_committed_migration, ResumeError
PLAN="a"*64
LOADER="26.1.2.109"
IID="test-minecraft"
AID="agent-test"

class ResumeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)/"instance"
  self.control=self.root/".dsm";self.control.mkdir(parents=True)
  self.journal={"phase":"committed","migration_plan_sha256":PLAN,"target_loader_version":LOADER}
  self.raw=(json.dumps(self.journal,sort_keys=True)+"\n").encode()
  self.sha=hashlib.sha256(self.raw).hexdigest()
  self.live=self.control/"minecraft-serverpack-migration.json"
  self.live.write_bytes(self.raw)
  self.op={"instance_id":IID,"agent_id":AID,"operation":"minecraft_serverpack_migration",
           "status":"finalization_pending","migration_plan_sha256":PLAN}
  self.detail={"status":"finalization_pending","trace":["committed","finalization_pending"],
               "migration_plan_sha256":PLAN,"target_loader_version":LOADER,
               "commit":{"initial_active_state":"active"}}
  self.prov={"instance_id":IID,"status":"running","current_step":"minecraft_serverpack_finalization",
             "finalization_state":"pending","minecraft_serverpack_migration":self.detail}
  self.state="inactive";self.events=[]
 def archive(self):
  self.events.append("archive")
  directory=self.control/"migration-history"/self.sha[:24]
  directory.mkdir(parents=True,exist_ok=True)
  self.live.replace(directory/"minecraft-serverpack-migration.json")
  (directory/"runtime.migration-rollback").mkdir(exist_ok=True)
  (self.control/"minecraft-serverpack-archive-checkpoint.json").write_text(
    json.dumps({"schema_version":1,"sha256":self.sha}))
  return {"status":"archived","sha256":self.sha}
 def restart(self,original):
  self.events.append("restore")
  self.state=original
  return original
 def observe(self):
  self.events.append("observe")
  return self.state
 def invoke(self):
  return resume_committed_migration(
   instance_root=self.root,operation=self.op,provisioning=self.prov,
   instance_id=IID,agent_id=AID,observe_service=self.observe,
   archive_committed=self.archive,restore_service=self.restart)
 def test_full_archive_then_restore(self):
  value=self.invoke()
  self.assertEqual(value["status"],"finalized")
  self.assertEqual(value["sha256"],self.sha)
  self.assertEqual(self.events.count("archive"),1)
  self.assertEqual(self.events.count("restore"),1)
 def test_crash_after_archive_replays_only_restart(self):
  self.archive();self.events.clear()
  value=self.invoke()
  self.assertEqual(value["archive_status"],"already_archived")
  self.assertNotIn("archive",self.events)
  self.assertEqual(self.events.count("restore"),1)
 def test_crash_after_restart_replays_without_changes(self):
  self.archive();self.state="active";self.events.clear()
  value=self.invoke()
  self.assertEqual(value["observed_state"],"active")
  self.assertNotIn("archive",self.events)
  self.assertNotIn("restore",self.events)
 def test_archive_must_not_run_while_active(self):
  self.state="active"
  with self.assertRaisesRegex(ResumeError,"stopped"):self.invoke()
  self.assertNotIn("archive",self.events)
 def test_unknown_service_state_refused(self):
  self.state="failed"
  with self.assertRaisesRegex(ResumeError,"ambiguous"):self.invoke()
 def test_wrong_agent_refused_before_actions(self):
  self.op["agent_id"]="other"
  with self.assertRaisesRegex(ResumeError,"identity"):self.invoke()
  self.assertEqual(self.events,[])
 def test_unknown_original_state_refused(self):
  self.detail["commit"].pop("initial_active_state")
  with self.assertRaisesRegex(ResumeError,"original"):self.invoke()
 def test_wrong_loader_refused(self):
  self.detail["target_loader_version"]="wrong"
  with self.assertRaisesRegex(ResumeError,"checkpoint"):self.invoke()
 def test_wrong_archive_digest_refused(self):
  old=self.archive
  self.archive=lambda: {"status":"archived","sha256":"b"*64}
  with self.assertRaisesRegex(ResumeError,"differs"):self.invoke()
 def test_corrupt_archive_refused(self):
  self.archive()
  directory=self.control/"migration-history"/self.sha[:24]
  (directory/"minecraft-serverpack-migration.json").write_text("tamper")
  with self.assertRaisesRegex(ResumeError,"checkpoint"):self.invoke()
 def test_failed_restart_preserves_pending(self):
  def broken(_):
   raise RuntimeError("game did not start")
  self.restart=broken
  with self.assertRaisesRegex(ResumeError,"restoration failed"):self.invoke()
  self.assertEqual(self.prov["status"],"running")
  self.assertEqual(self.op["status"],"finalization_pending")
 def test_inactive_original_never_starts(self):
  self.detail["commit"]["initial_active_state"]="inactive"
  value=self.invoke()
  self.assertEqual(value["observed_state"],"inactive")
  self.assertNotIn("restore",self.events)
 def test_not_committed_denied(self):
  self.journal["phase"]="swapped";self.live.write_text(json.dumps(self.journal))
  with self.assertRaisesRegex(ResumeError,"checkpoint"):self.invoke()
 def test_missing_rollback_denied(self):
  self.archive()
  (self.control/"migration-history"/self.sha[:24]/"runtime.migration-rollback").rmdir()
  with self.assertRaisesRegex(ResumeError,"checkpoint"):self.invoke()

if __name__=="__main__":unittest.main()
