"""Injected-effects verification of Agent completion ordering and failure boundaries."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/"agents/linux/runtime"))
from minecraft_serverpack_finalization_completion import finish_pending_migration, CompletionError

PLAN="a"*64
LOADER="26.1.2.109"


class FinishTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)/"instance"
  ctl=self.root/".dsm";ctl.mkdir(parents=True)
  self.raw=(json.dumps({"phase":"committed","migration_plan_sha256":PLAN,
                        "target_loader_version":LOADER},sort_keys=True)+"\n").encode()
  self.digest=hashlib.sha256(self.raw).hexdigest()
  self.journal=ctl/"minecraft-serverpack-migration.json";self.journal.write_bytes(self.raw)
  self.op={"instance_id":"test001","agent_id":"agent001","operation":"minecraft_serverpack_migration",
           "status":"finalization_pending","migration_plan_sha256":PLAN}
  self.detail={"status":"finalization_pending","migration_plan_sha256":PLAN,
               "target_loader_version":LOADER,"trace":["committed","finalization_pending"],
               "backup":{"backup_id":"backup-1","sha256":"b"*64,"integrity_verified":True},
               "commit":{"initial_active_state":"active"}}
  self.res={"provisioning_id":"provision-1","instance_id":"test001","status":"running",
            "current_step":"minecraft_serverpack_finalization",
            "finalization_state":"pending","minecraft_serverpack_migration":self.detail}
  self.service="inactive";self.events=[]
  self.backup_valid=True
  self.fail_at=None
 def archive(self):
  self.events.append("archive")
  if self.fail_at=="archive":raise RuntimeError("failed archive")
  control=self.root/".dsm"
  directory=control/"migration-history"/self.digest[:24]
  directory.mkdir(parents=True,exist_ok=True)
  self.journal.replace(directory/"minecraft-serverpack-migration.json")
  (directory/"runtime.migration-rollback").mkdir(exist_ok=True)
  (control/"minecraft-serverpack-archive-checkpoint.json").write_text(
    json.dumps({"schema_version":1,"sha256":self.digest}))
  return {"status":"archived","sha256":self.digest}
 def restore(self,state):
  self.events.append("restart")
  if self.fail_at=="restart":raise RuntimeError("restart failed")
  self.service=state;return state
 def publish(self,value):
  self.events.append("provisioning")
  if self.fail_at=="publish":raise RuntimeError("disk failure")
  self.res=dict(value)
 def complete(self,value):
  self.events.append("operation")
  if self.fail_at=="operation":raise RuntimeError("outer disk failure")
  self.op=dict(value)
 def invoke(self):
  return finish_pending_migration(
   instance_id="test001",agent_id="agent001",instance_root=self.root,
   operation=dict(self.op),provisioning=dict(self.res),
   verify_backup=lambda _:self.backup_valid,
   observe_service=lambda:self.service,
   archive_committed=self.archive,restore_service=self.restore,
   write_provisioning=self.publish,write_operation=self.complete)
 def test_happy_path_order(self):
  self.assertEqual(self.invoke()["status"],"completed")
  self.assertEqual(self.events,["archive","restart","provisioning","operation"])
  self.assertEqual(self.res["status"],"completed")
  self.assertEqual(self.res["observed_state"],"running")
  self.assertEqual(self.op["status"],"completed")
 def test_prearchived_replay_does_not_rearchive(self):
  self.archive();self.events.clear()
  self.assertEqual(self.invoke()["status"],"completed")
  self.assertEqual(self.events,["restart","provisioning","operation"])
 def test_replay_after_result_publication_only_finishes_outer(self):
  self.fail_at="operation"
  with self.assertRaises(RuntimeError):self.invoke()
  self.assertEqual(self.res["status"],"completed")
  self.fail_at=None
  self.events.clear()
  self.assertEqual(self.invoke()["status"],"operation_reconciled")
  self.assertEqual(self.events,["operation"])
 def test_backup_missing_blocks_before_archive(self):
  self.backup_valid=False
  with self.assertRaisesRegex(CompletionError,"backup"):self.invoke()
  self.assertEqual(self.events,[])
 def test_archive_error_never_publishes(self):
  self.fail_at="archive"
  with self.assertRaises(RuntimeError):self.invoke()
  self.assertNotIn("provisioning",self.events)
  self.assertEqual(self.op["status"],"finalization_pending")
 def test_restart_error_never_publishes(self):
  self.fail_at="restart"
  with self.assertRaises(RuntimeError):self.invoke()
  self.assertNotIn("provisioning",self.events)
  self.assertEqual(self.op["status"],"finalization_pending")
 def test_publish_error_keeps_operation_pending(self):
  self.fail_at="publish"
  with self.assertRaises(RuntimeError):self.invoke()
  self.assertEqual(self.op["status"],"finalization_pending")
  self.assertNotIn("operation",self.events)
 def test_unknown_original_state_denied(self):
  self.detail["commit"].pop("initial_active_state")
  with self.assertRaises(Exception):self.invoke()
  self.assertEqual(self.events,[])
 def test_inactive_original_is_not_started(self):
  self.detail["commit"]["initial_active_state"]="inactive"
  self.invoke()
  self.assertNotIn("restart",self.events)
  self.assertEqual(self.res["observed_state"],"stopped")

if __name__=="__main__":unittest.main()
