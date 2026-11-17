#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/"agents/common"
if str(COMMON) not in sys.path:sys.path.insert(0,str(COMMON))
spec=importlib.util.spec_from_file_location(
 "minecraft_serverpack_migration_adapter",
 COMMON/"minecraft_serverpack_migration_adapter.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def digest(path:Path)->str:
 return hashlib.sha256(path.read_bytes()).hexdigest()


class MinecraftServerPackMigrationAdapterTest(unittest.TestCase):
 def make_zip(self,root:Path)->Path:
  archive=root/"ServerFiles.zip"
  with zipfile.ZipFile(archive,"w") as z:
   z.writestr("mods/a.jar",b"a")
   z.writestr("config/general.toml","x=1\n")
  return archive

 def migration(self,archive:Path)->dict:
  return {
   "archive_sha256":digest(archive),
   "archive_size_bytes":archive.stat().st_size,
   "serverpack_prefix":"",
   "serverpack_mod_count":1,
   "serverpack_override_dirs":["config"],
   "migration_plan_sha256":"b"*64,
   "minecraft_version":"26.1.2",
   "target_loader_version":"26.1.2.109",
   "isolated_install_dir":"instance-abcd-2612109",
  }

 def selection(self)->dict:
  return {
   "runtime_definition":"minecraft.java.neoforge",
   "game":"minecraft","version":"26.1.2","build":"26.1.2.109",
   "tag":"26.1.2.109","install_dir":"instance-abcd-2612109",
   "provider":"http",
   "installer":{"type":"java_jar"},
   "asset":{
    "sha256":"e7b68f389a7d6855d706c3471f66df4fcf0e403bd483b09f67678016e2d80280",
    "url":"https://maven.neoforged.net/releases/net/neoforged/neoforge/26.1.2.109/neoforge-26.1.2.109-installer.jar",
   },
  }

 def test_exact_catalog_selection_is_bound_to_staged_serverpack(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);archive=self.make_zip(root)
   result=module.prepare_migration_inputs(
    archive=archive,stage_root=root/"stage",
    migration=self.migration(archive),selection=self.selection())
   self.assertEqual(result["target_loader_version"],"26.1.2.109")
   self.assertEqual(result["serverpack_staging"]["mods"],1)
   self.assertEqual(result["isolated_install_dir"],"instance-abcd-2612109")
   self.assertEqual(
    result["neoforge_installer_sha256"],
    "e7b68f389a7d6855d706c3471f66df4fcf0e403bd483b09f67678016e2d80280")
   self.assertFalse(result["execution_authorized"])

 def test_mismatched_loader_version_install_dir_provider_or_url_fail_closed(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);archive=self.make_zip(root);migration=self.migration(archive)
   cases=(
    {"version":"26.1.1"},
    {"build":"26.1.2.110","tag":"26.1.2.110"},
    {"install_dir":"other-dir"},
    {"provider":"github"},
    {"asset":{"sha256":"e7b68f389a7d6855d706c3471f66df4fcf0e403bd483b09f67678016e2d80280",
              "url":"https://example.com/neoforge-26.1.2.109-installer.jar"}},
   )
   for index,mutation in enumerate(cases):
    with self.subTest(index=index):
     selection={**self.selection(),**mutation}
     with self.assertRaises(module.MinecraftServerPackMigrationAdapterError):
      module.prepare_migration_inputs(
       archive=archive,stage_root=root/f"stage-{index}",
       migration=migration,selection=selection)

 def test_invalid_installer_sha_or_runtime_identity_fail_closed(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);archive=self.make_zip(root);migration=self.migration(archive)
   cases=(
    {"runtime_definition":"minecraft.java.fabric"},
    {"game":"dayz"},
    {"installer":{"type":"shell"}},
    {"asset":{"sha256":"bad","url":"https://maven.neoforged.net/releases/net/neoforged/neoforge/26.1.2.109/neoforge-26.1.2.109-installer.jar"}},
   )
   for index,mutation in enumerate(cases):
    with self.subTest(index=index):
     with self.assertRaises(module.MinecraftServerPackMigrationAdapterError):
      module.prepare_migration_inputs(
       archive=archive,stage_root=root/f"stage-{index}",
       migration=migration,selection={**self.selection(),**mutation})


if __name__=="__main__":unittest.main()
