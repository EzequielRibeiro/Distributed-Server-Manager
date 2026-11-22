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


 def test_finalization_child_sh_blocks_coordinator_ex_until_completion(self):
  """Grouped real two-PID flock proof, all operational work mocked."""
  import subprocess
  import threading
  from unittest.mock import Mock
  from types import SimpleNamespace
  import game_uptime_finalization_admission as admission
  import game_uptime_finalization_flock as fence

  folder=self.root/"trusted"
  folder.mkdir(mode=0o755)
  lock=folder/"agent-finalization-operations.lock"
  uid,gid=os.geteuid(),os.getegid()
  fence.provision_finalization_lock(
      path=lock,trusted_uid=uid,group_gid=gid)
  assert lock.stat().st_size == 0
  # No opt-in must preserve the installed behavior.
  with fence.shared_finalization_lock(path=lock,enabled=False,
                                      trusted_uid=uid,group_gid=gid) as enabled:
   self.assertFalse(enabled)

  def shared():
   return fence.shared_finalization_lock(
       path=lock,enabled=True,trusted_uid=uid,group_gid=gid)

  probe="""
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[2])
from game_uptime_finalization_flock import (
    exclusive_finalization_lock,FinalizationFenceUnavailable)
try:
    with exclusive_finalization_lock(
            path=Path(sys.argv[1]),trusted_uid=int(sys.argv[3]),
            group_gid=int(sys.argv[4])) as state:
        assert state["live_no_drain_authorized"] is False
        assert state["external_jobs_acked"] is False
        print("FREE")
except FinalizationFenceUnavailable:
    print("BUSY")
"""

  def exclusive_probe():
   result=subprocess.run(
       [sys.executable,"-c",probe,str(lock),
        str(R/"agents/linux/runtime"),str(uid),str(gid)],
       capture_output=True,text=True,check=True,timeout=12)
   return result.stdout.strip()

  self.assertEqual(exclusive_probe(),"FREE")
  ready=threading.Event()
  release=threading.Event()
  finished=[]
  errors=[]
  dispatched=Mock()
  def scan(**_kwargs):
   ready.set()
   if not release.wait(timeout=12):
    raise AssertionError("detached-child fence fixture timed out")
   return []

  def child():
   try:
    finished.extend(w.execute_one(self.cfg,"sandbox-instance"))
   except BaseException as exc:
    errors.append(exc)

  fake={"minecraft_serverpack_finalization_dispatcher":
        SimpleNamespace(dispatch_published_completion=dispatched)}
  with patch.dict(os.environ,self.env,clear=True), \
       patch.dict(sys.modules,fake), \
       patch.object(admission,"observe",return_value={"active":False}), \
       patch.object(w,"shared_finalization_lock",side_effect=shared), \
       patch.object(w,"scan_pending_finalizations",side_effect=scan):
   t=threading.Thread(target=child,daemon=True)
   try:
    t.start()
    self.assertTrue(ready.wait(timeout=12))
    self.assertEqual(exclusive_probe(),"BUSY")
   finally:
    release.set()
    t.join(timeout=12)
   self.assertFalse(t.is_alive())
  self.assertEqual(errors,[])
  self.assertEqual(finished,[])
  dispatched.assert_not_called()
  self.assertEqual(exclusive_probe(),"FREE")

  # EX ownership denies new children before reading provisioning journals.
  scan=Mock()
  with patch.dict(os.environ,self.env,clear=True), \
       patch.dict(sys.modules,fake), \
       patch.object(admission,"observe",return_value={"active":False}), \
       patch.object(w,"shared_finalization_lock",side_effect=shared), \
       patch.object(w,"scan_pending_finalizations",scan):
   with fence.exclusive_finalization_lock(
       path=lock,trusted_uid=uid,group_gid=gid):
    with self.assertRaises(fence.FinalizationFenceUnavailable):
     w.execute_one(self.cfg,"sandbox-instance")
  scan.assert_not_called()

  # Hold that appears after initial admission is caught inside the SH.
  with patch.dict(os.environ,self.env,clear=True), \
       patch.dict(sys.modules,fake), \
       patch.object(admission,"observe",
                    side_effect=[{"active":False},{"active":True}]), \
       patch.object(w,"shared_finalization_lock",side_effect=shared), \
       patch.object(w,"scan_pending_finalizations",scan):
   with self.assertRaises(admission.FinalizationMaintenanceHold):
    w.execute_one(self.cfg,"sandbox-instance")
  scan.assert_not_called()

  # Unsafe inode can never be interpreted as idle, or silently repaired.
  lock.chmod(0o666)
  try:
   with self.assertRaises(fence.FinalizationFenceUnavailable):
    with shared():
     self.fail("unsafe lock accepted")
  finally:
   lock.chmod(0o660)
  self.assertEqual(exclusive_probe(),"FREE")

if __name__=="__main__":unittest.main()
