"""Actual one-shot worker process, disk-backed Agent state and OS file locks.

No Minecraft instance or production state is touched. Proves crash/replay and
authorization with a standalone Agent runtime operating inside TemporaryDirectory.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/"agents/linux/runtime"
WORKER=RUNTIME/"minecraft_serverpack_finalization_worker.py"
PLAN="a"*64
IID="pr855-subprocess-e2e"
AID="pr839-isolated-agent"
PID="e2e-provision"

class FinalizationWorkerProcessE2E(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(prefix="dsm-pr981-e2e-")
  self.addCleanup(self.t.cleanup)
  self.root=Path(self.t.name)
  self.state=self.root/"agent-state"
  for name in ("instance-provisioning","instance-operations","instances"):
   (self.state/name).mkdir(parents=True)
  self.storage=self.root/"isolated-storage"/IID
  (self.storage/"runtime").mkdir(parents=True)
  self.hist=self.storage/".dsm"/"migration-history"
  self.hist.mkdir(parents=True)
  journal={"phase":"committed","migration_plan_sha256":PLAN,"target_loader_version":"26.1.2.109"}
  raw=(json.dumps(journal)+"\n").encode()
  digest=hashlib.sha256(raw).hexdigest()
  archived=self.hist/digest[:24];archived.mkdir()
  (archived/"minecraft-serverpack-migration.json").write_bytes(raw)
  self.config=self.root/"agent-config.json"
  self.config.write_text(json.dumps({"agent_id":AID}))
  self.config.chmod(0o600)
  self.record={
   "instance_id":IID,"agent_id":AID,"game_id":"minecraft",
   "environment_id":"minecraft.java.neoforge",
   "instance_state_root":str(self.storage),
   "working_directory":str(self.storage/"runtime"),
  }
  (self.state/"instances"/(IID+".json")).write_text(json.dumps(self.record))
  self.outer={
   "instance_id":IID,"agent_id":AID,"operation":"minecraft_serverpack_migration",
   "migration_plan_sha256":PLAN,"status":"finalization_pending",
  }
  self.operation=self.state/"instance-operations"/(IID+".json")
  self.operation.write_text(json.dumps(self.outer))
  self.detail={
   "migration_plan_sha256":PLAN,"target_loader_version":"26.1.2.109",
   "status":"completed","trace":["committed","finalized"],
   "finalization":{"status":"archived","sha256":digest},
  }
  self.result={
   "provisioning_id":PID,"instance_id":IID,"status":"completed",
   "minecraft_serverpack_migration":self.detail,
  }
  self.provision=self.state/"instance-provisioning"/(PID+".result.json")
  self.provision.write_text(json.dumps(self.result))
  self.env={**os.environ,
   "CAPIVARA_AGENT_STATE_DIR":str(self.state),
   "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE":IID,
   "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE":"1",
   "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER":"0",
  }
 def child(self,instance=IID,env=None):
  return subprocess.run([sys.executable,str(WORKER),str(self.config),instance],
   env=env or self.env,capture_output=True,text=True,timeout=20)
 def test_worker_reconciles_real_files_then_is_idempotent(self):
  first=self.child()
  self.assertEqual(first.returncode,0,first.stderr+first.stdout)
  self.assertEqual(json.loads(self.operation.read_text())["status"],"completed")
  self.assertEqual(json.loads(self.provision.read_text())["status"],"completed")
  second=self.child()
  self.assertEqual(second.returncode,0,second.stderr+second.stdout)
  self.assertEqual(json.loads(self.operation.read_text())["status"],"completed")
  self.assertFalse(list(self.root.rglob("*.tmp")))
 def test_killed_official_worker_replays_verified_archive(self):
  """Hard-stop the actual worker before it can publish; replay its disk state."""
  import signal
  worker=subprocess.Popen(
   [sys.executable,str(WORKER),str(self.config),IID],
   env=self.env,stdin=subprocess.DEVNULL,
   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
   start_new_session=True,
  )
  try:
   os.kill(worker.pid,signal.SIGSTOP)
   os.kill(worker.pid,signal.SIGKILL)
   out,err=worker.communicate(timeout=5)
   self.assertNotEqual(worker.returncode,0,(out,err))
   self.assertEqual(json.loads(self.operation.read_text())["status"],"finalization_pending")
   self.assertEqual(json.loads(self.provision.read_text())["status"],"completed")
   first=self.child()
   self.assertEqual(first.returncode,0,first.stderr+first.stdout)
   self.assertEqual(json.loads(self.operation.read_text())["status"],"completed")
   self.assertEqual(json.loads(self.provision.read_text())["status"],"completed")
   replay=self.child()
   self.assertEqual(replay.returncode,0,replay.stderr+replay.stdout)
   self.assertEqual(json.loads(self.operation.read_text())["status"],"completed")
   self.assertEqual(len(list(self.hist.glob("*/minecraft-serverpack-migration.json"))),1)
  finally:
   if worker.poll() is None:
    worker.kill()
    worker.wait(timeout=5)
 def test_real_committed_archive_with_official_worker(self):
  """Real swap/archive checkpoint, then the actual one-shot worker replays ACK."""
  import shutil
  sys.path.insert(0,str(ROOT/"agents/common"))
  from minecraft_serverpack_migration_swap import prepare,switch,commit,archive_committed
  shutil.rmtree(self.hist)
  active=self.storage/"runtime"
  (active/"world").mkdir()
  (active/"world/level.dat").write_bytes(b"ORIGINAL_TEST_WORLD")
  staged=self.storage/"runtime.migration-stage"
  canonical=staged/"libraries/net/neoforged/neoforge/26.1.2.109/unix_args.txt"
  canonical.parent.mkdir(parents=True)
  canonical.write_text("--neoforge-build 26.1.2.109\n")
  (staged/"capivara-launch.args").write_bytes(canonical.read_bytes())
  (staged/"world").mkdir()
  (staged/"world/level.dat").write_bytes(b"NEW_TEST_WORLD")
  backup={"backup_id":"retained-test","sha256":"d"*64,"size_bytes":123,
          "integrity_verified":True}
  prepare(self.storage,migration_plan_sha256=PLAN,
          target_loader_version="26.1.2.109",backup=backup)
  switch(self.storage)
  commit(self.storage,readiness_passed=True)
  archived=archive_committed(self.storage)
  self.detail["finalization"]={"status":archived["status"],"sha256":archived["sha256"]}
  self.provision.write_text(json.dumps(self.result))
  outcome=self.child()
  self.assertEqual(outcome.returncode,0,outcome.stderr+outcome.stdout)
  self.assertEqual(json.loads(self.operation.read_text())["status"],"completed")
  self.assertEqual((self.storage/"runtime/world/level.dat").read_bytes(),b"NEW_TEST_WORLD")
  self.assertEqual(
   next(self.hist.glob("*/runtime.migration-rollback/world/level.dat")).read_bytes(),
   b"ORIGINAL_TEST_WORLD")
  self.assertEqual(len(list(self.hist.glob("*/minecraft-serverpack-migration.json"))),1)
  replay=self.child()
  self.assertEqual(replay.returncode,0,replay.stderr+replay.stdout)
  self.assertEqual(json.loads(self.operation.read_text())["status"],"completed")
 def test_wrong_instance_never_mutates(self):
  outcome=self.child("not-authorized")
  self.assertNotEqual(outcome.returncode,0)
  self.assertEqual(json.loads(self.operation.read_text())["status"],"finalization_pending")
 def test_invalid_history_checksum_never_releases(self):
  digest=self.detail["finalization"]["sha256"]
  (self.hist/digest[:24]/"minecraft-serverpack-migration.json").write_text("tampered")
  outcome=self.child()
  self.assertNotEqual(outcome.returncode,0)
  self.assertEqual(json.loads(self.operation.read_text())["status"],"finalization_pending")
 def test_disabled_flag_never_mutates(self):
  env={**self.env,"CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE":"0"}
  outcome=self.child(env=env)
  self.assertNotEqual(outcome.returncode,0)
  self.assertEqual(json.loads(self.operation.read_text())["status"],"finalization_pending")
 def test_external_lock_denies_concurrent_worker_then_replays(self):
  # Real flock held by an independent child, not a unittest fake lock.
  lock_path=self.state/"instance-locks"/(IID+".lock")
  lock_path.parent.mkdir()
  ready=self.root/"lock-ready"
  holder=subprocess.Popen([sys.executable,"-c",
   "import fcntl,os,pathlib,sys,time; p=pathlib.Path(sys.argv[1]);"
   " f=p.open('a+'); fcntl.flock(f,fcntl.LOCK_EX);"
   " pathlib.Path(sys.argv[2]).write_text('ready'); time.sleep(15)",
   str(lock_path),str(ready)],
   stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
  try:
   deadline=time.monotonic()+5
   while not ready.exists() and time.monotonic()<deadline:
    time.sleep(0.03)
   self.assertTrue(ready.exists(),"independent lock holder did not start")
   blocked=self.child()
   self.assertNotEqual(blocked.returncode,0)
   self.assertEqual(json.loads(self.operation.read_text())["status"],"finalization_pending")
  finally:
   holder.kill()
   holder.wait(timeout=5)
   if holder.stderr is not None:
    holder.stderr.close()
  recovered=self.child()
  self.assertEqual(recovered.returncode,0,recovered.stderr+recovered.stdout)
  self.assertEqual(json.loads(self.operation.read_text())["status"],"completed")

if __name__=="__main__":
 unittest.main()
