"""Integration of real file-backed Agent records and fail-closed dispatcher."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/linux/runtime"))
import minecraft_serverpack_finalization_dispatcher as dispatch
import minecraft_serverpack_finalization_scheduler as scheduler
from contextlib import contextmanager

PLAN="a"*64
IID="isolated-minecraft-test"
AID="agent-test"


class DispatcherTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.root=Path(self.t.name)
  self.state=self.root/"agent-state"
  self.provision=self.state/"instance-provisioning"
  self.operations=self.state/"instance-operations"
  self.provision.mkdir(parents=True);self.operations.mkdir()
  self.instance=self.root/"instances"/IID
  (self.instance/"runtime").mkdir(parents=True)
  history=self.instance/".dsm"/"migration-history"
  history.mkdir(parents=True)
  self.journal={"phase":"committed","migration_plan_sha256":PLAN,"target_loader_version":"26.1.2.109"}
  raw=(json.dumps(self.journal)+"\n").encode()
  digest=hashlib.sha256(raw).hexdigest()
  archived=history/digest[:24];archived.mkdir()
  (archived/"minecraft-serverpack-migration.json").write_bytes(raw)
  self.outer={"agent_id":AID,"instance_id":IID,"operation":"minecraft_serverpack_migration",
              "status":"finalization_pending","migration_plan_sha256":PLAN}
  self.result={"instance_id":IID,"provisioning_id":"test-provision",
               "status":"completed",
               "minecraft_serverpack_migration":{
                   "status":"completed","migration_plan_sha256":PLAN,
                   "target_loader_version":"26.1.2.109","trace":["committed","finalized"],
                   "finalization":{"status":"archived","sha256":digest}}}
  self.record={"instance_id":IID,"agent_id":AID,"game_id":"minecraft",
               "instance_state_root":str(self.instance),
               "working_directory":str(self.instance/"runtime")}
  self.opath=self.operations/(IID+".json")
  self.rpath=self.provision/"test-provision.result.json"
  self.flush()
  self.mock=patch.multiple(dispatch,get_instance=lambda _:dict(self.record),
                           operation_path=lambda _:self.opath,
                           paths=lambda _: (self.provision/"test-provision.request.json",self.rpath,self.provision/"test-provision.log"))
  self.mock.start();self.addCleanup(self.mock.stop)
 def flush(self):
  self.opath.write_text(json.dumps(self.outer))
  self.rpath.write_text(json.dumps(self.result))
 def invoke(self,authorized=IID):
  return dispatch.dispatch_published_completion(self.outer,self.result,
          agent_id=AID,allowed_instance_id=authorized)
 def test_valid_completion_reconciles_idempotently(self):
  self.assertEqual(self.invoke()["status"],"operation_reconciled")
  self.outer=json.loads(self.opath.read_text())
  self.assertEqual(self.outer["status"],"completed")
  self.assertEqual(self.invoke()["status"],"already_completed")
 def test_wrong_allowlist_denied(self):
  with self.assertRaises(dispatch.FinalizationDispatchError):self.invoke("other")
  self.assertEqual(json.loads(self.opath.read_text())["status"],"finalization_pending")
 def test_running_result_denied(self):
  self.result["status"]="running";self.flush()
  with self.assertRaises(dispatch.FinalizationDispatchError):self.invoke()
 def test_wrong_registered_owner_denied(self):
  self.record["agent_id"]="other"
  with self.assertRaises(dispatch.FinalizationDispatchError):self.invoke()
 def test_wrong_registered_game_denied(self):
  self.record["game_id"]="dayz"
  with self.assertRaises(dispatch.FinalizationDispatchError):self.invoke()
 def test_runtime_path_mismatch_denied(self):
  self.record["working_directory"]=str(self.root/"alien")
  with self.assertRaises(dispatch.FinalizationDispatchError):self.invoke()
 def test_tampered_archive_denied_without_mutation(self):
  self.journal["target_loader_version"]="other"
  digest=self.result["minecraft_serverpack_migration"]["finalization"]["sha256"]
  (self.instance/".dsm"/"migration-history"/digest[:24]/"minecraft-serverpack-migration.json").write_text(json.dumps(self.journal))
  with self.assertRaises(Exception):self.invoke()
  self.assertEqual(json.loads(self.opath.read_text())["status"],"finalization_pending")
 def test_scan_under_instance_lock_dispatches_after_verified_success(self):
  events=[]
  @contextmanager
  def lock(iid):
   events.append("lock")
   yield
   events.append("unlock")
  result=scheduler.scan_pending_finalizations(state_root=self.state,agent_id=AID,
   lock_instance=lock,read_operation=lambda _:json.loads(self.opath.read_text()),
   dispatch=lambda op,res: dispatch.dispatch_published_completion(
    op,res,agent_id=AID,allowed_instance_id=IID),
   enabled=True)
  self.assertEqual(result[0]["status"],"dispatched")
  self.assertEqual(events,["lock","unlock"])
  self.assertEqual(json.loads(self.opath.read_text())["status"],"completed")
 def test_disabled_scan_never_modifies_operation(self):
  result=scheduler.scan_pending_finalizations(state_root=self.state,agent_id=AID,
   lock_instance=lambda _: _NoopLock(),read_operation=lambda _:self.outer)
  self.assertEqual(result[0]["status"],"pending_journal_reconciliation")
  self.assertEqual(json.loads(self.opath.read_text())["status"],"finalization_pending")


class _NoopLock:
 def __enter__(self):return self
 def __exit__(self,*args):return False


if __name__=="__main__":unittest.main()
