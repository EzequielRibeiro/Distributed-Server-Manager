#!/usr/bin/env python3
from __future__ import annotations
import hashlib,stat,sys,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"core"))
from minecraft_serverpack import MinecraftServerPackError,inspect_serverpack

def pack(path,entries):
 with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as archive:
  for name,value in entries.items():archive.writestr(name,value)

class ServerPackInspectionTest(unittest.TestCase):
 def sample(self,path,**kwargs):
  return inspect_serverpack(path,"26.1.2","neoforge",
      embedded_loader_version="26.1.2.109",**kwargs)

 def test_valid_official_layout_selects_only_mods_and_whitelisted_configs(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/"ServerFiles-0.9.0-beta.zip"
   entries={"settings.cfg":"MCVER=26.1.2\nMODLOADER=neoforge\nNEOFORGE_VERSION=26.1.2.109\n",
            "mods/example.jar":b"jar-one","mods/other.jar":b"jar-two",
            "config/cfg.toml":"allow=true","kubejs/server_scripts/test.js":"function(){ }",
            "ServerStart.sh":"#!/bin/bash\nrm -rf /\n",
            "README.txt":"Official release notes"}
   pack(path,entries)
   found=self.sample(path)
   self.assertEqual(found["count"],2)
   self.assertEqual(found["loader_version"],"26.1.2.109")
   self.assertEqual(found["override_dirs"],["config","kubejs"])
   self.assertIn("ServerStart.sh",found["ignored_executables"])
   self.assertEqual(found["sha256"],hashlib.sha256(path.read_bytes()).hexdigest())
   self.assertEqual(found["members"][0]["sha256"],hashlib.sha256(b"jar-one").hexdigest())

 def test_wrapper_folder_is_supported_without_install_scripts(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/"wrapped.zip"
   pack(path,{"Release/settings.cfg":"MCVER=26.1.2\nFORGEVER=26.1.2.109\nMODLOADER=neoforge",
              "Release/mods/example.jar":"jar","Release/config/a.toml":"x=1"})
   found=self.sample(path)
   self.assertEqual(found["members"][0]["archive_member"],"Release/mods/example.jar")
   self.assertEqual(found["override_dirs"],["config"])

 def test_rejects_wrong_game_loader_build_and_unpinned_ambiguous_version(self):
  for settings,declared,installed in (
     ("MCVER=26.1.1\nMODLOADER=neoforge\nNEOFORGE_VERSION=26.1.2.109","", "26.1.2.109"),
     ("MCVER=26.1.2\nMODLOADER=fabric\nNEOFORGE_VERSION=26.1.2.109","", "26.1.2.109"),
     ("MCVER=26.1.2\nMODLOADER=neoforge\nNEOFORGE_VERSION=26.1.2.99","", "26.1.2.109"),
     ("MCVER=26.1.2\nMODLOADER=neoforge","", "26.1.2.109"),
  ):
   with self.subTest(settings=settings),tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/"pack.zip";pack(path,{"settings.cfg":settings,"mods/a.jar":"jar"})
    with self.assertRaises(MinecraftServerPackError):
     inspect_serverpack(path,"26.1.2","neoforge",embedded_loader_version=installed,
                        declared_loader_version=declared)

 def test_missing_internal_loader_can_be_pinned_explicitly(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/"pack.zip"
   pack(path,{"mods/a.jar":"jar"})
   found=self.sample(path,declared_loader_version="26.1.2.109")
   self.assertEqual(found["loader_version"],"26.1.2.109")

 def test_traversal_symlinks_duplicates_unknown_mods_are_rejected(self):
  cases=[
   {"../escape.txt":"bad","mods/a.jar":"a","settings.cfg":"MCVER=26.1.2\nMODLOADER=neoforge\nNEOFORGE_VERSION=26.1.2.109"},
   {"mods/a.jar":"a","mods/a.txt":"bad","settings.cfg":"MCVER=26.1.2\nMODLOADER=neoforge\nNEOFORGE_VERSION=26.1.2.109"},
   {"mods/a.jar":"a","mods/../mods/b.jar":"b","settings.cfg":"MCVER=26.1.2\nMODLOADER=neoforge\nNEOFORGE_VERSION=26.1.2.109"},
  ]
  for entries in cases:
   with self.subTest(entries=entries),tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/"bad.zip";pack(path,entries)
    with self.assertRaises(MinecraftServerPackError):self.sample(path)
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/"symlink.zip"
   with zipfile.ZipFile(path,"w") as archive:
    entry=zipfile.ZipInfo("mods/link.jar");entry.create_system=3
    entry.external_attr=(stat.S_IFLNK | 0o777) <<16
    archive.writestr(entry,"/etc/passwd")
   with self.assertRaises(MinecraftServerPackError):self.sample(path)

if __name__=="__main__":unittest.main()
