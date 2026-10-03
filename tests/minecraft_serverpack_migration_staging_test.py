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
 "minecraft_serverpack_migration_staging",
 COMMON/"minecraft_serverpack_migration_staging.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def sha256(path:Path)->str:
 return hashlib.sha256(path.read_bytes()).hexdigest()


class MinecraftServerPackMigrationStagingTest(unittest.TestCase):
 def make_zip(self,root:Path,*,unsafe=False):
  archive=root/"ServerFiles.zip"
  with zipfile.ZipFile(archive,"w") as z:
   if unsafe:
    z.writestr("../escape.txt","bad")
   else:
    z.writestr("mods/a.jar",b"a")
    z.writestr("mods/b.jar",b"b")
    z.writestr("config/general.toml","x=1\n")
    z.writestr("kubejs/server_scripts/example.js","// data script\n")
    z.writestr("startserver.sh","echo never-run\n")
  return archive

 def migration(self,archive:Path):
  return {
   "archive_sha256":sha256(archive),
   "archive_size_bytes":archive.stat().st_size,
   "serverpack_prefix":"",
   "serverpack_mod_count":2,
   "serverpack_override_dirs":["config","kubejs"],
  }

 def test_safe_stage_keeps_launchers_inert_and_projects_only_allowed_content(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);archive=self.make_zip(root);stage=root/"stage"
   result=module.stage_serverpack_archive(archive,stage,self.migration(archive))
   self.assertEqual(result["mods"],2)
   self.assertEqual(result["override_dirs"],["config","kubejs"])
   self.assertFalse(result["executable_projection"])
   self.assertTrue((stage/"mods/a.jar").is_file())
   self.assertTrue((stage/"server-overrides/config/general.toml").is_file())
   self.assertTrue((stage/"server-overrides/kubejs/server_scripts/example.js").is_file())
   self.assertTrue((stage/"startserver.sh").is_file())
   self.assertFalse((stage/"config").exists())
   self.assertRegex(result["tree_sha256"],r"^[0-9a-f]{64}$")

 def test_hash_size_and_structure_mismatch_fail_closed(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);archive=self.make_zip(root)
   cases=[
    {**self.migration(archive),"archive_sha256":"0"*64},
    {**self.migration(archive),"archive_size_bytes":archive.stat().st_size+1},
    {**self.migration(archive),"serverpack_mod_count":3},
    {**self.migration(archive),"serverpack_override_dirs":["config","missing"]},
   ]
   for index,migration in enumerate(cases):
    with self.subTest(index=index):
     stage=root/f"stage-{index}"
     with self.assertRaises(module.MinecraftServerPackMigrationStagingError):
      module.stage_serverpack_archive(archive,stage,migration)

 def test_path_traversal_and_nonempty_stage_are_rejected(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);archive=self.make_zip(root,unsafe=True);stage=root/"stage"
   with self.assertRaisesRegex(
    module.MinecraftServerPackMigrationStagingError,"unsafe path"):
    module.stage_serverpack_archive(archive,stage,self.migration(archive))
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);archive=self.make_zip(root);stage=root/"stage";stage.mkdir()
   (stage/"sentinel").write_text("keep")
   with self.assertRaisesRegex(
    module.MinecraftServerPackMigrationStagingError,"must be empty"):
    module.stage_serverpack_archive(archive,stage,self.migration(archive))
   self.assertEqual((stage/"sentinel").read_text(),"keep")


if __name__=="__main__":unittest.main()
