"""Agent callback wiring to real disk files with mocked privileged and service effects."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/linux/runtime"))
import minecraft_serverpack_finalization_operational as operational
from minecraft_serverpack_finalization_dispatcher import FinalizationDispatchError

PLAN="a"*64
LOADER="26.1.2.109"
IID="test-minecraft"
AID="agent-test"

class FakeAdapter:
 name="systemd"
 def __init__(self,case):self.case=case
 def status(self,_):return {"available":True,"active_state":self.case.state}
 def start(self,_):
  self.case.events.append("start")
  self.case.state="active"

class OperationalTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.base=Path(self.t.name)
  self.root=self.base/"storage"/IID
  self.control=self.root/".dsm";self.control.mkdir(parents=True)
  self.runtime=self.root/"runtime";self.runtime.mkdir()
  raw=(json.dumps({"phase":"committed","migration_plan_sha256":PLAN,"target_loader_version":LOADER},sort_keys=True)+"\n").encode()
  self.sha=hashlib.sha256(raw).hexdigest()
  self.live=self.control/"minecraft-serverpack-migration.json";self.live.write_bytes(raw)
  self.opath=self.base/"instance-operations"/(IID+".json");self.opath.parent.mkdir()
  self.rpath=self.base/"instance-provisioning"/"prov-1.result.json";self.rpath.parent.mkdir()
  self.op={"instance_id":IID,"agent_id":AID,"operation":"minecraft_serverpack_migration",
           "status":"finalization_pending","migration_plan_sha256":PLAN}
  self.res={"provisioning_id":"prov-1","instance_id":IID,"status":"running",
            "current_step":"minecraft_serverpack_finalization","finalization_state":"pending",
            "minecraft_serverpack_migration":{
             "status":"finalization_pending","trace":["committed","finalization_pending"],
             "migration_plan_sha256":PLAN,"target_loader_version":LOADER,
             "commit":{"initial_active_state":"active"},
             "backup":{"backup_id":"backup-1","sha256":"b"*64,"size_bytes":120,"integrity_verified":True}}}
  self.record={"instance_id":IID,"agent_id":AID,"game_id":"minecraft",
               "environment_id":"minecraft.java.neoforge",
               "instance_state_root":str(self.root),"working_directory":str(self.runtime)}
  self.events=[];self.state="inactive";self.bad_backup=False
  self.write()
  self.patches=[
   patch.object(operational,"get_instance",lambda _:self.record),
   patch.object(operational,"resolve_adapter",lambda _:FakeAdapter(self)),
   patch.object(operational,"paths",lambda _: (self.base/"req",self.rpath,self.base/"log")),
   patch.object(operational,"operation_path",lambda _:self.opath),
   patch.object(operational,"_attest_retained_backup",lambda *_:{
      "integrity_verified":True,"sha256":"0"*64 if self.bad_backup else "b"*64,"size_bytes":120}),
   patch.object(operational,"minecraft_serverpack_swap_phase",self.archive),
   patch.object(operational,"_readiness_log_baseline",lambda *_:None),
   patch.object(operational,"_wait_for_done",lambda *_1,**_2:True),
  ]
  for p in self.patches:
   p.start();self.addCleanup(p.stop)
 def write(self):
  self.opath.write_text(json.dumps(self.op))
  self.rpath.write_text(json.dumps(self.res))
 def archive(self,*a,**kw):
  self.events.append("archive")
  destination=self.control/"migration-history"/self.sha[:24]
  destination.mkdir(parents=True)
  self.live.replace(destination/"minecraft-serverpack-migration.json")
  (destination/"runtime.migration-rollback").mkdir()
  (self.control/"minecraft-serverpack-archive-checkpoint.json").write_text(
   json.dumps({"schema_version":1,"sha256":self.sha}))
  return {"status":"archived","sha256":self.sha}
 def invoke(self,allowed=IID):
  return operational.recover_pending_operational(
   config={"agent_id":AID},operation=self.op,provisioning=self.res,allowed_instance_id=allowed)
 def test_end_to_end_durable_journal_order(self):
  self.assertEqual(self.invoke()["status"],"completed")
  self.assertEqual(self.events,["archive","start"])
  self.assertEqual(json.loads(self.opath.read_text())["status"],"completed")
  self.assertEqual(json.loads(self.rpath.read_text())["status"],"completed")
 def test_backup_mismatch_blocks_everything(self):
  self.bad_backup=True
  with self.assertRaises(Exception):self.invoke()
  self.assertEqual(self.events,[])
  self.assertEqual(json.loads(self.opath.read_text())["status"],"finalization_pending")
 def test_allowlist_blocks_everything(self):
  with self.assertRaises(FinalizationDispatchError):self.invoke("foreign")
  self.assertEqual(self.events,[])
 def test_modified_provisioning_rejected(self):
  self.rpath.write_text(json.dumps({**self.res,"progress":1}))
  with self.assertRaises(FinalizationDispatchError):self.invoke()
  self.assertEqual(self.events,[])
 def test_other_game_rejected(self):
  self.record["game_id"]="dayz"
  with self.assertRaises(FinalizationDispatchError):self.invoke()
 def test_non_systemd_adapter_rejected(self):
  class Other:
   name="other"
  with patch.object(operational,"resolve_adapter",lambda _:Other()):
   with self.assertRaises(FinalizationDispatchError):self.invoke()
 def test_unknown_state_never_archives(self):
  self.state="failed"
  with self.assertRaises(Exception):self.invoke()
  self.assertNotIn("archive",self.events)
 def test_existing_archive_resume_does_not_archive_again(self):
  self.archive();self.events.clear()
  self.assertEqual(self.invoke()["status"],"completed")
  self.assertEqual(self.events,["start"])

if __name__=="__main__":unittest.main()
