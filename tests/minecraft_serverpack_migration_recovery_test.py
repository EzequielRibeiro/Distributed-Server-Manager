#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]


class RecoveryCoordinatorTest(unittest.TestCase):
 def setUp(self):
  self.saved={name:sys.modules.get(name) for name in (
   "instance_runtime","runtime_lock","runtime_operations",
   "minecraft_serverpack_migration_swap")}
 def tearDown(self):
  for name,value in self.saved.items():
   if value is None:sys.modules.pop(name,None)
   else:sys.modules[name]=value

 def load(self,platform,outer,recover_result=None,recover_error=None,path_exists=True):
  state={"writes":[],"locks":[]}
  instance_runtime=types.ModuleType("instance_runtime")
  instance_runtime._token=lambda value,label:str(value)
  sys.modules["instance_runtime"]=instance_runtime

  runtime_lock=types.ModuleType("runtime_lock")
  @contextmanager
  def instance_lock(iid,operation,timeout_seconds=5.0):
   state["locks"].append((iid,operation,timeout_seconds));yield
  runtime_lock.instance_lock=instance_lock
  sys.modules["runtime_lock"]=runtime_lock

  temporary=Path(tempfile.mkdtemp())/"outer.json"
  if path_exists:temporary.write_text("{}")
  runtime_operations=types.ModuleType("runtime_operations")
  runtime_operations.read_operation=lambda iid: None if outer is None else dict(outer)
  runtime_operations._path=lambda iid:temporary
  runtime_operations._now=lambda:"2026-10-03T13:00:00Z"
  def atomic(path,payload):
   state["writes"].append(dict(payload))
  runtime_operations._atomic=atomic
  sys.modules["runtime_operations"]=runtime_operations

  swap=types.ModuleType("minecraft_serverpack_migration_swap")
  def recover(root):
   if recover_error is not None:raise recover_error
   return dict(recover_result or {
    "status":"recovered","failed_runtime_retained":True})
  swap.recover=recover
  sys.modules["minecraft_serverpack_migration_swap"]=swap

  path=ROOT/"agents"/platform/"runtime"/"minecraft_serverpack_migration_recovery.py"
  spec=importlib.util.spec_from_file_location(f"recovery_{platform}_{id(self)}",path)
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  return module,state

 def test_linux_and_windows_coordinator_are_identical(self):
  self.assertEqual(
   (ROOT/"agents/linux/runtime/minecraft_serverpack_migration_recovery.py").read_bytes(),
   (ROOT/"agents/windows/runtime/minecraft_serverpack_migration_recovery.py").read_bytes())

 def test_failed_outer_journal_is_cleared_only_after_verified_filesystem_recovery(self):
  outer={"agent_id":"agent-a","instance_id":"i1",
         "operation":"minecraft_serverpack_migration","status":"failed",
         "error":"readiness failed"}
  for platform in ("linux","windows"):
   with self.subTest(platform=platform):
    module,state=self.load(platform,outer)
    result=module.recover_minecraft_serverpack_migration(
     {"agent_id":"agent-a"},"i1",instance_state_root=Path("/isolated"))
    self.assertEqual(result["status"],"recovered")
    self.assertEqual(len(state["writes"]),1)
    written=state["writes"][0]
    self.assertEqual(written["status"],"recovered")
    self.assertNotIn("error",written)
    self.assertTrue(written["recovery"]["failed_runtime_retained"])
    self.assertFalse(written["recovery"]["manual_recovery_required"])
    self.assertEqual(state["locks"][0][1],"minecraft_serverpack_migration_recovery")

 def test_filesystem_recovery_failure_keeps_outer_barrier(self):
  outer={"agent_id":"agent-a","operation":"minecraft_serverpack_migration",
         "status":"interrupted","error":"restart"}
  module,state=self.load("linux",outer,recover_error=RuntimeError("bad rollback"))
  with self.assertRaisesRegex(
   module.MinecraftServerPackMigrationRecoveryError,
   "could not prove restoration"):
   module.recover_minecraft_serverpack_migration(
    {"agent_id":"agent-a"},"i1",instance_state_root=Path("/isolated"))
  self.assertEqual(state["writes"],[])

 def test_non_failed_or_unrelated_operation_is_never_cleared(self):
  cases=(
   {"agent_id":"agent-a","operation":"minecraft_serverpack_migration","status":"completed"},
   {"agent_id":"agent-a","operation":"backup","status":"failed"},
   {"agent_id":"agent-b","operation":"minecraft_serverpack_migration","status":"failed"},
  )
  for index,outer in enumerate(cases):
   with self.subTest(index=index):
    module,state=self.load("linux",outer)
    with self.assertRaises(module.MinecraftServerPackMigrationRecoveryError):
     module.recover_minecraft_serverpack_migration(
      {"agent_id":"agent-a"},"i1",instance_state_root=Path("/isolated"))
    self.assertEqual(state["writes"],[])

 def test_recovered_outer_journal_is_idempotent_without_touching_filesystem(self):
  outer={"agent_id":"agent-a","operation":"minecraft_serverpack_migration",
         "status":"recovered"}
  module,state=self.load("linux",outer,recover_error=AssertionError("must not call"))
  result=module.recover_minecraft_serverpack_migration(
   {"agent_id":"agent-a"},"i1",instance_state_root=Path("/isolated"))
  self.assertEqual(result["status"],"already_recovered")
  self.assertEqual(state["writes"],[])


if __name__=="__main__":unittest.main()
