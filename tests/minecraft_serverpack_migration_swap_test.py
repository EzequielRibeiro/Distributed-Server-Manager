#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
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


if __name__=="__main__":unittest.main()
