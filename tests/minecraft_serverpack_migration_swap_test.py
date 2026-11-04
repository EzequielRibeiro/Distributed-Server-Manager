#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/"agents/common"
if str(COMMON) not in sys.path:sys.path.insert(0,str(COMMON))
spec=importlib.util.spec_from_file_location(
 "minecraft_serverpack_migration_swap",
 COMMON/"minecraft_serverpack_migration_swap.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

BACKUP={"backup_id":"backup-1","sha256":"d"*64,"size_bytes":1234,"integrity_verified":True}


def runtime(root:Path,version:str,marker:bytes)->Path:
 root.mkdir(parents=True)
 libs=root/"libraries/net/neoforged/neoforge"/version
 libs.mkdir(parents=True)
 args=libs/"unix_args.txt";args.write_bytes(b"--loader "+version.encode()+b"\n")
 (root/"capivara-launch.args").write_bytes(args.read_bytes())
 (root/"user_jvm_args.txt").write_text("-Xmx1G\n")
 (root/"world").mkdir();(root/"world/level.dat").write_bytes(marker)
 return root


class SwapTest(unittest.TestCase):
 def make(self,base:Path):
  runtime(base/"runtime","26.1.2.94",b"OLD")
  runtime(base/"runtime.migration-stage","26.1.2.109",b"NEW")
  return base

 def test_success_swap_requires_readiness_and_retains_rollback(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name))
   prepared=module.prepare(root,migration_plan_sha256="b"*64,
    target_loader_version="26.1.2.109",backup=BACKUP)
   self.assertEqual(prepared["phase"],"prepared")
   switched=module.switch(root);self.assertEqual(switched["phase"],"swapped")
   self.assertEqual((root/"runtime/world/level.dat").read_bytes(),b"NEW")
   self.assertEqual((root/"runtime.migration-rollback/world/level.dat").read_bytes(),b"OLD")
   with self.assertRaisesRegex(module.MinecraftServerPackMigrationSwapError,"readiness"):
    module.commit(root,readiness_passed=False)
   result=module.commit(root,readiness_passed=True)
   self.assertEqual(result["status"],"committed")
   self.assertTrue(result["rollback_retained"])
   with self.assertRaisesRegex(module.MinecraftServerPackMigrationSwapError,"cannot be silently recovered"):
    module.recover(root)

 def test_readiness_may_change_world_config_and_logs_but_not_managed_loader_or_mods(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name))
   (root/"runtime.migration-stage/mods").mkdir(exist_ok=True)
   (root/"runtime.migration-stage/mods/a.jar").write_bytes(b"A")
   module.prepare(root,migration_plan_sha256="b"*64,
    target_loader_version="26.1.2.109",backup=BACKUP)
   module.switch(root)
   active=root/"runtime"
   (active/"world/level.dat").write_bytes(b"NEW-WORLD-STATE")
   (active/"server.properties").write_text("motd=changed by runtime\n")
   (active/"logs").mkdir(exist_ok=True);(active/"logs/latest.log").write_text("Done\n")
   result=module.commit(root,readiness_passed=True)
   self.assertEqual(result["status"],"committed")

 def test_managed_mod_tamper_after_readiness_blocks_commit(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name))
   (root/"runtime.migration-stage/mods").mkdir(exist_ok=True)
   jar=root/"runtime.migration-stage/mods/a.jar";jar.write_bytes(b"A")
   module.prepare(root,migration_plan_sha256="b"*64,
    target_loader_version="26.1.2.109",backup=BACKUP)
   module.switch(root)
   (root/"runtime/mods/a.jar").write_bytes(b"TAMPER")
   with self.assertRaisesRegex(
    module.MinecraftServerPackMigrationSwapError,
    "managed runtime changed"):
    module.commit(root,readiness_passed=True)

 def test_failed_candidate_recovers_original_and_retains_failed_tree(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name))
   module.prepare(root,migration_plan_sha256="b"*64,
    target_loader_version="26.1.2.109",backup=BACKUP)
   module.switch(root)
   result=module.recover(root)
   self.assertEqual(result["status"],"recovered")
   self.assertTrue(result["failed_runtime_retained"])
   self.assertEqual((root/"runtime/world/level.dat").read_bytes(),b"OLD")
   self.assertEqual((root/"runtime.migration-failed/world/level.dat").read_bytes(),b"NEW")
   again=module.recover(root);self.assertEqual(again["status"],"already_recovered")

 def test_tree_change_after_prepare_blocks_switch(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name))
   module.prepare(root,migration_plan_sha256="b"*64,
    target_loader_version="26.1.2.109",backup=BACKUP)
   (root/"runtime.migration-stage/tamper.txt").write_text("changed")
   with self.assertRaisesRegex(module.MinecraftServerPackMigrationSwapError,"changed after"):
    module.switch(root)
   self.assertTrue((root/"runtime").is_dir())
   self.assertTrue((root/"runtime.migration-stage").is_dir())

 def test_invalid_backup_and_existing_transaction_artifacts_fail_closed(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name))
   bad={**BACKUP,"integrity_verified":False}
   with self.assertRaisesRegex(module.MinecraftServerPackMigrationSwapError,"verified backup"):
    module.prepare(root,migration_plan_sha256="b"*64,
     target_loader_version="26.1.2.109",backup=bad)
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name));(root/"runtime.migration-rollback").mkdir()
   with self.assertRaisesRegex(module.MinecraftServerPackMigrationSwapError,"occupied"):
    module.prepare(root,migration_plan_sha256="b"*64,
     target_loader_version="26.1.2.109",backup=BACKUP)

 def test_wrong_loader_candidate_fails_before_journal(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name)
   runtime(root/"runtime","26.1.2.94",b"OLD")
   runtime(root/"runtime.migration-stage","26.1.2.108",b"NEW")
   with self.assertRaises(Exception):
    module.prepare(root,migration_plan_sha256="b"*64,
     target_loader_version="26.1.2.109",backup=BACKUP)
   self.assertFalse((root/".dsm/minecraft-serverpack-migration.json").exists())


 def test_consecutive_committed_migration_is_archivable_with_rollback_retained(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name))
   module.prepare(root,migration_plan_sha256="b"*64,target_loader_version="26.1.2.109",backup=BACKUP)
   module.switch(root)
   module.commit(root,readiness_passed=True)
   archived=module.archive_committed(root)
   self.assertEqual(archived["status"],"archived")
   history=Path(archived["history"])
   self.assertTrue((history/"minecraft-serverpack-migration.json").exists())
   self.assertEqual((history/"runtime.migration-rollback/world/level.dat").read_bytes(),b"OLD")
   runtime(root/"runtime.migration-stage","26.1.2.124",b"NEWER")
   next_tx=module.prepare(root,migration_plan_sha256="c"*64,target_loader_version="26.1.2.124",backup=BACKUP)
   self.assertEqual(next_tx["phase"],"prepared")

 def test_incomplete_migration_is_not_archived(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name))
   module.prepare(root,migration_plan_sha256="b"*64,target_loader_version="26.1.2.109",backup=BACKUP)
   with self.assertRaisesRegex(module.MinecraftServerPackMigrationSwapError,"only committed"):
    module.archive_committed(root)


 def _commit_first(self,root):
  module.prepare(root,migration_plan_sha256="b"*64,target_loader_version="26.1.2.109",backup=BACKUP)
  module.switch(root)
  module.commit(root,readiness_passed=True)

 def test_archive_is_idempotent_after_success(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name));self._commit_first(root)
   first=module.archive_committed(root)
   second=module.archive_committed(root)
   self.assertEqual(second["status"],"already_archived")
   self.assertEqual(first["sha256"],second["sha256"])

 def test_resume_after_rollback_rename_crash(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name));self._commit_first(root)
   original=module.os.replace
   def interrupt(src,dst):
    if str(src).endswith("minecraft-serverpack-migration.json"):
     raise OSError("simulated crash after rollback move")
    return original(src,dst)
   with patch.object(module.os,"replace",side_effect=interrupt):
    with self.assertRaisesRegex(OSError,"simulated crash"):
     module.archive_committed(root)
   self.assertFalse((root/"runtime.migration-rollback").exists())
   self.assertTrue((root/".dsm/minecraft-serverpack-migration.json").exists())
   self.assertEqual(module.archive_committed(root)["status"],"archived")
   self.assertEqual(module.archive_committed(root)["status"],"already_archived")

 def test_resume_after_journal_rename_crash(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name));self._commit_first(root)
   original=module._sync_dir
   def interrupt(path):
    if path==root/".dsm" and not (path/"minecraft-serverpack-migration.json").exists():
     raise OSError("simulated crash after journal move")
    return original(path)
   with patch.object(module,"_sync_dir",side_effect=interrupt):
    with self.assertRaisesRegex(OSError,"simulated crash"):
     module.archive_committed(root)
   self.assertFalse((root/".dsm/minecraft-serverpack-migration.json").exists())
   self.assertEqual(module.archive_committed(root)["status"],"already_archived")

 def test_three_consecutive_updates_preserve_world_and_history(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name));self._commit_first(root)
   self.assertEqual(module.archive_committed(root)["status"],"archived")
   for index,version in enumerate(("26.1.2.124","26.1.2.130")):
    marker=("world-"+str(index)).encode()
    runtime(root/"runtime.migration-stage",version,marker)
    module.prepare(root,migration_plan_sha256=("c" if index==0 else "d")*64,target_loader_version=version,backup=BACKUP)
    module.switch(root)
    module.commit(root,readiness_passed=True)
    self.assertEqual((root/"runtime/world/level.dat").read_bytes(),marker)
    self.assertEqual(module.archive_committed(root)["status"],"archived")
   history=list((root/".dsm/migration-history").iterdir())
   self.assertEqual(len(history),3)
   self.assertTrue(all((p/"runtime.migration-rollback/world/level.dat").exists() for p in history))
   self.assertFalse((root/"runtime.migration-rollback").exists())
   self.assertFalse((root/".dsm/minecraft-serverpack-migration.json").exists())

 def test_reject_tampered_archive_checkpoint(self):
  with tempfile.TemporaryDirectory() as name:
   root=self.make(Path(name));self._commit_first(root)
   module.archive_committed(root)
   (root/".dsm/minecraft-serverpack-archive-checkpoint.json").write_text('{"schema_version":1,"sha256":"bad"}')
   with self.assertRaisesRegex(module.MinecraftServerPackMigrationSwapError,"invalid archival checkpoint"):
    module.archive_committed(root)



if __name__=="__main__":unittest.main()
