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
 "minecraft_serverpack_migration_runtime_stage",
 COMMON/"minecraft_serverpack_migration_runtime_stage.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def loader_seed(root:Path,version:str)->Path:
 root.mkdir(parents=True)
 libs=root/"libraries/net/neoforged/neoforge"/version
 libs.mkdir(parents=True)
 args=(libs/"unix_args.txt")
 args.write_text(f"--loader {version}\n")
 (root/"capivara-launch.args").write_bytes(args.read_bytes())
 (root/"user_jvm_args.txt").write_text("-Xmx2G\n")
 (root/"eula.txt").write_text("eula=true\n")
 (root/"run.sh").write_text("# inert\n")
 (root/"run.bat").write_text("@rem inert\n")
 return root


class RuntimeStageTest(unittest.TestCase):
 def make_active(self,root:Path)->Path:
  active=loader_seed(root/"active","26.1.2.94")
  (active/"mods").mkdir();(active/"mods/old.jar").write_bytes(b"old")
  (active/"world").mkdir();(active/"world/level.dat").write_bytes(b"WORLD")
  (active/"config").mkdir();(active/"config/customer.toml").write_text("keep=true\n")
  (active/"kubejs").mkdir();(active/"kubejs/local.js").write_text("// keep\n")
  (active/"server.properties").write_text("motd=customer\n")
  return active

 def make_pack(self,root:Path)->Path:
  pack=root/"pack";(pack/"mods").mkdir(parents=True)
  (pack/"mods/new-a.jar").write_bytes(b"a")
  (pack/"mods/new-b.jar").write_bytes(b"b")
  (pack/"server-overrides/config").mkdir(parents=True)
  (pack/"server-overrides/config/default.toml").write_text("replace=false\n")
  return pack

 def test_candidate_replaces_loader_and_mods_but_preserves_private_state(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);active=self.make_active(root);seed=loader_seed(root/"new","26.1.2.109");pack=self.make_pack(root)
   result=module.build_staged_runtime(
    active_runtime=active,target_loader_seed=seed,serverpack_stage=pack,
    destination=root/"candidate",target_loader_version="26.1.2.109")
   candidate=root/"candidate"
   self.assertEqual(result["mods"],2)
   self.assertTrue(result["existing_config_preserved"])
   self.assertTrue(result["world_preserved"])
   self.assertFalse(result["activated"])
   self.assertEqual((candidate/"world/level.dat").read_bytes(),b"WORLD")
   self.assertEqual((candidate/"config/customer.toml").read_text(),"keep=true\n")
   self.assertEqual((candidate/"kubejs/local.js").read_text(),"// keep\n")
   self.assertEqual((candidate/"server.properties").read_text(),"motd=customer\n")
   self.assertFalse((candidate/"mods/old.jar").exists())
   self.assertTrue((candidate/"mods/new-a.jar").is_file())
   self.assertFalse((candidate/"server-overrides").exists())
   self.assertTrue((candidate/"libraries/net/neoforged/neoforge/26.1.2.109").is_dir())
   self.assertFalse((candidate/"libraries/net/neoforged/neoforge/26.1.2.94").exists())

 def test_wrong_loader_seed_or_existing_destination_fails_closed(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);active=self.make_active(root);seed=loader_seed(root/"new","26.1.2.108");pack=self.make_pack(root)
   with self.assertRaises(module.MinecraftServerPackRuntimeStageError):
    module.build_staged_runtime(active_runtime=active,target_loader_seed=seed,
     serverpack_stage=pack,destination=root/"candidate",target_loader_version="26.1.2.109")
   destination=root/"exists";destination.mkdir()
   seed2=loader_seed(root/"new2","26.1.2.109")
   with self.assertRaisesRegex(module.MinecraftServerPackRuntimeStageError,"must not already exist"):
    module.build_staged_runtime(active_runtime=active,target_loader_seed=seed2,
     serverpack_stage=pack,destination=destination,target_loader_version="26.1.2.109")

 def test_symlink_in_active_tree_is_rejected(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);active=self.make_active(root);seed=loader_seed(root/"new","26.1.2.109");pack=self.make_pack(root)
   (active/"bad-link").symlink_to(active/"world")
   with self.assertRaisesRegex(module.MinecraftServerPackRuntimeStageError,"symbolic link"):
    module.build_staged_runtime(active_runtime=active,target_loader_seed=seed,
     serverpack_stage=pack,destination=root/"candidate",target_loader_version="26.1.2.109")


if __name__=="__main__":unittest.main()
