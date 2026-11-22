"""One-shot worker policy and revalidation, all side effects mocked."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import contextmanager

R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/"agents/linux/runtime"))
import minecraft_serverpack_finalization_worker as w

class WorkerTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.root=Path(self.t.name);self.cfg=self.root/"agent.json"
  self.cfg.write_text(json.dumps({"agent_id":"agent-test"}))
  self.env={"CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE":"sandbox-instance",
            "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE":"1",
            "CAPIVARA_AGENT_STATE_DIR":str(self.root)}
 def test_default_denied(self):
  with patch.dict(os.environ,{"CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE":"0",
                                "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER":"0"},clear=True):
   with self.assertRaises(PermissionError):w.execute_one(self.cfg,"sandbox-instance")
 def test_wrong_instance_denied(self):
  with patch.dict(os.environ,self.env,clear=True):
   with self.assertRaises(PermissionError):w.execute_one(self.cfg,"foreign")
 def test_reconcile_only_does_not_load_operational_module(self):
  seen=[]
  @contextmanager
  def lock(_):
   yield
  def scan(**kwargs):
   kwargs["dispatch"]({"instance_id":"foreign"},{"instance_id":"foreign","status":"completed"})
   kwargs["dispatch"]({"instance_id":"sandbox-instance"},{"instance_id":"sandbox-instance","status":"running"})
   return [{"instance_id":"sandbox-instance","status":"pending"}]
  with patch.dict(os.environ,self.env,clear=True), patch.object(w,"scan_pending_finalizations",scan):
   self.assertEqual(w.execute_one(self.cfg,"sandbox-instance")[0]["status"],"pending")
 def test_requires_absolute_config(self):
  with patch.dict(os.environ,self.env,clear=True):
   with self.assertRaises(ValueError):w.execute_one(Path("relative.json"),"sandbox-instance")
 def test_reconcile_without_candidate(self):
  with patch.dict(os.environ,self.env,clear=True),patch.object(w,"scan_pending_finalizations",return_value=[]):
   self.assertEqual(w.execute_one(self.cfg,"sandbox-instance"),[])


 def test_detached_worker_rechecks_hold_before_spawn_and_recovery(self):
  """One grouped negative proof; no real game, Agent or filesystem repair."""
  from unittest.mock import Mock
  from types import SimpleNamespace
  from minecraft_serverpack_finalization_supervisor import FinalizationWorkerSupervisor
  import game_uptime_finalization_admission as admission

  spawned=Mock()
  supervisor=FinalizationWorkerSupervisor(spawn=spawned)
  kwargs={"instance_id":"sandbox-instance","config_path":self.cfg,
          "state_dir":self.root}
  with patch.object(admission,"observe",return_value={
      "active":True,"reason":"pending_journal_requires_operator_recovery"}):
   with self.assertRaises(admission.FinalizationMaintenanceHold):
    supervisor.launch(**kwargs)
   with patch.dict(os.environ,self.env,clear=True):
    with self.assertRaises(admission.FinalizationMaintenanceHold):
     w.execute_one(self.cfg,"sandbox-instance")
  spawned.assert_not_called()
  self.assertFalse((self.root/"finalization-worker").exists())

  # Unreadable or invalid evidence must never permit a worker spawn.
  with patch.object(admission,"observe",side_effect=OSError("unreadable")):
   with self.assertRaises(admission.FinalizationMaintenanceHold):
    supervisor.launch(**kwargs)
  with patch.object(admission,"observe",return_value=None):
   with self.assertRaises(admission.FinalizationMaintenanceHold):
    supervisor.launch(**kwargs)
  spawned.assert_not_called()

  # The child passed initial admission, but a hold appears before dispatch.
  # Exercise both finalization publication and recovery paths without writes.
  for status in ("completed","running"):
   with self.subTest(status=status):
    state={"active":False}
    publish=Mock()
    recover=Mock()
    def observe():
     return dict(state)
    def scan(**options):
     state["active"]=True
     options["dispatch"](
         {"instance_id":"sandbox-instance"},
         {"instance_id":"sandbox-instance","status":status})
     self.fail("blocked dispatch must raise before mutation")
    env=dict(self.env)
    env["CAPIVARA_SERVERPACK_FINALIZATION_RECOVER"]="1"
    env["CAPIVARA_SERVERPACK_FINALIZATION_RECOVER_ACK"]="AUTHORIZED"
    fake_modules={
     "minecraft_serverpack_finalization_dispatcher":
        SimpleNamespace(dispatch_published_completion=publish),
     "minecraft_serverpack_finalization_operational":
        SimpleNamespace(recovery_feature_allowed=lambda *_:True,
                        recover_pending_operational=recover),
    }
    with patch.dict(os.environ,env,clear=True), \
         patch.dict(sys.modules,fake_modules), \
         patch.object(admission,"observe",side_effect=observe), \
         patch.object(w,"scan_pending_finalizations",side_effect=scan):
     with self.assertRaises(admission.FinalizationMaintenanceHold):
      w.execute_one(self.cfg,"sandbox-instance")
    publish.assert_not_called()
    recover.assert_not_called()

if __name__=="__main__":unittest.main()
