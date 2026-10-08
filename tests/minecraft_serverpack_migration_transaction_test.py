#!/usr/bin/env python3
"""Transactional sequencing tests for staged NeoForge + Server Pack migrations."""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
VALID={
 "kind":"MinecraftServerPackMigration","schema_version":1,
 "instance_id":"pr855-node1-homolog","content_id":"atm11",
 "transfer_id":"transfer-abc","filename":"ServerFiles-0.9.0-beta.zip",
 "archive_sha256":"a"*64,"archive_size_bytes":518936896,
 "serverpack_prefix":"","serverpack_mod_count":254,
 "serverpack_override_dirs":["config","kubejs"],
 "migration_plan_sha256":"b"*64,"previous_bundle_revision":3,
 "previous_manifest_sha256":"c"*64,
 "from_loader_version":"26.1.2.94","target_loader_version":"26.1.2.109",
 "minecraft_version":"26.1.2","isolated_install_dir":"instance-test-2612109",
 "backup_before_update":True,"preserve_world":True,"install_allowed":False,
}
BACKUP={"backup_id":"backup-1","sha256":"d"*64,"size_bytes":706389174,
        "integrity_verified":True}


def load(platform):
 path=ROOT/"agents"/platform/"runtime"/"minecraft_serverpack_migration_transaction.py"
 runtime_dir=str(path.parent)
 if runtime_dir not in sys.path:sys.path.insert(0,runtime_dir)
 spec=importlib.util.spec_from_file_location(f"migration_transaction_{platform}",path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module


class TransactionTest(unittest.TestCase):
 def test_linux_windows_transaction_core_is_identical(self):
  self.assertEqual(
   (ROOT/"agents/linux/runtime/minecraft_serverpack_migration_transaction.py").read_bytes(),
   (ROOT/"agents/windows/runtime/minecraft_serverpack_migration_transaction.py").read_bytes())

 def _run(self,platform="linux",fail_at=None,rollback_fail=False,revalidate_sha=None,backup=None):
  module=load(platform);events=[];locks=[]
  @contextmanager
  def fake_operation(config,instance_id,operation,lock_timeout_seconds=5.0):
   locks.append((instance_id,operation,lock_timeout_seconds));events.append("lock")
   try:
    yield {}
   finally:
    events.append("unlock")
  module.runtime_operation=fake_operation
  def hook(name,result=None):
   def call(*args):
    events.append(name)
    if fail_at==name:raise RuntimeError("injected "+name)
    return result
   return call
  hooks={
   "revalidate":hook("revalidate",{"valid":True,"install_allowed":False,
     "migration_plan_sha256":revalidate_sha or VALID["migration_plan_sha256"]}),
   "capacity":hook("capacity",{"sufficient":True,"install_allowed":False,
     "requires_exclusive_recheck":True}),
   "backup":hook("backup",backup or BACKUP),
   "stop":hook("stop"),"stage":hook("stage"),"swap":hook("swap"),
   "readiness":hook("readiness",False if fail_at=="readiness_false" else True),
   "commit":hook("commit",{"revision_commit_ready":True}),
  }
  def rollback(*args):
   events.append("rollback")
   if rollback_fail:raise RuntimeError("rollback injected")
  hooks["rollback"]=rollback
  return module,events,locks,hooks

 def test_success_order_and_lock(self):
  for platform in ("linux","windows"):
   module,events,locks,hooks=self._run(platform)
   result=module.execute_minecraft_serverpack_migration(
    {"agent_id":"agent-test"},VALID["instance_id"],VALID,hooks)
   self.assertEqual(result["status"],"completed")
   self.assertEqual(result["backup"]["backup_id"],"backup-1")
   self.assertEqual(result["trace"],
    ["contract_validated","revalidated","capacity_checked","backup_verified",
     "stopped","staged","swapped","ready","committed"])
   self.assertEqual(events,
    ["lock","revalidate","capacity","backup","stop","stage","swap","readiness","commit","unlock"])
   self.assertEqual(locks[0][1],"minecraft_serverpack_migration")

 def test_fingerprint_change_blocks_before_backup_or_mutation(self):
  module,events,_,hooks=self._run(revalidate_sha="e"*64)
  with self.assertRaisesRegex(module.MinecraftServerPackMigrationExecutionError,
                              "fingerprint changed"):
   module.execute_minecraft_serverpack_migration(
    {"agent_id":"agent-test"},VALID["instance_id"],VALID,hooks)
  self.assertNotIn("backup",events);self.assertNotIn("stage",events)

 def test_invalid_backup_blocks_before_stop(self):
  module,events,_,hooks=self._run(
   backup={"backup_id":"backup-1","sha256":"d"*64,"size_bytes":1,
           "integrity_verified":False})
  with self.assertRaisesRegex(module.MinecraftServerPackMigrationExecutionError,
                              "independently verified"):
   module.execute_minecraft_serverpack_migration(
    {"agent_id":"agent-test"},VALID["instance_id"],VALID,hooks)
  self.assertNotIn("stop",events);self.assertNotIn("stage",events)

 def test_failure_after_staging_rolls_back_inside_lock(self):
  for failure in ("stage","swap","readiness_false","commit"):
   with self.subTest(failure=failure):
    module,events,_,hooks=self._run(fail_at=failure)
    with self.assertRaises(module.MinecraftServerPackMigrationExecutionError) as ctx:
     module.execute_minecraft_serverpack_migration(
      {"agent_id":"agent-test"},VALID["instance_id"],VALID,hooks)
    if failure=="stage":
     self.assertNotIn("rollback",events)
    else:
     self.assertIn("rollback",events)
     self.assertLess(events.index("rollback"),events.index("unlock"))
     self.assertIn("rolled_back",ctx.exception.trace)

 def test_rollback_failure_requires_manual_recovery(self):
  module,events,_,hooks=self._run(fail_at="commit",rollback_fail=True)
  with self.assertRaisesRegex(module.MinecraftServerPackMigrationExecutionError,
                              "manual recovery required") as ctx:
   module.execute_minecraft_serverpack_migration(
    {"agent_id":"agent-test"},VALID["instance_id"],VALID,hooks)
  self.assertIn("rollback_failed",ctx.exception.trace)
  self.assertLess(events.index("rollback"),events.index("unlock"))


if __name__=="__main__":unittest.main()
