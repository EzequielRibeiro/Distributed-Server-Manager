#!/usr/bin/env python3
"""CurseForge server modpacks exclude known client resources, never unknown ones."""
import hashlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"core"))
from minecraft_modpack_resolver import resolve_curseforge_modpack
from minecraft_content_resolver import MinecraftContentResolverError
from content_bundle import normalize_bundle

class ClientOnlyCurseForgeManifestTest(unittest.TestCase):
 def fixture(self,entries,classes):
  manifest={"manifestType":"minecraftModpack","manifestVersion":1,
    "minecraft":{"version":"26.1.2","modLoaders":[{"id":"neoforge-26.1.2.11","primary":True}]},
    "files":[{"projectID":ident,"fileID":ident+5000,"required":True} for ident in entries]}
  out=io.BytesIO()
  with zipfile.ZipFile(out,"w") as pack:pack.writestr("manifest.json",json.dumps(manifest))
  archive=out.getvalue();archive_hash=hashlib.sha1(archive).hexdigest()
  calls=[]
  def requester(url,headers):
   calls.append(url)
   if "/categories?" in url:
    return {"data":[{"id":4471,"isClass":True,"slug":"modpacks","name":"Modpacks"},
      {"id":6,"isClass":True,"slug":"mc-mods","name":"Mods"},
      {"id":6552,"isClass":True,"slug":"shaders","name":"Shaders"},
      {"id":12,"isClass":True,"slug":"texture-packs","name":"Resource Packs"},
      {"id":17,"isClass":True,"slug":"worlds","name":"Worlds"}]}
   if url.endswith("/mods/1148445"):
    return {"data":{"id":1148445,"gameId":432,"classId":4471}}
   if "/mods/1148445/files?" in url:
    return {"data":[{"id":999,"fileName":"atm11.zip","displayName":"ATM11",
      "isAvailable":True,"gameVersions":["26.1.2","NeoForge"],"fileDate":"2026-09-01",
      "downloadUrl":"https://edge.forgecdn.net/atm11.zip","hashes":[{"algo":1,"value":archive_hash}]}]}
   if "/mods/" in url:
    parts=url.split("/mods/",1)[1].split("/")
    ident=int(parts[0])
    if ident not in classes:raise AssertionError("Unrequested project: "+url)
    category,game=classes[ident]
    if len(parts)==1:
     return {"data":{"id":ident,"gameId":game,"classId":category}}
    if len(parts)==3 and parts[1]=="files":
     file_id=int(parts[2])
     assert file_id==ident+5000
     return {"data":{"id":file_id,"isAvailable":True,
       "fileName":"mod.jar","displayName":"Mod 1","gameVersions":["26.1.2","NeoForge"],
       "downloadUrl":"https://edge.forgecdn.net/mod.jar",
       "hashes":[{"algo":1,"value":"a"*40}]}}
   raise AssertionError("Unexpected provider request: "+url)
  def resolve(runtime=None):
   return resolve_curseforge_modpack("1148445","atm11","26.1.2",
     runtime or {"loader":"neoforge"},api_key="test-secret",requester=requester,
     bytes_requester=lambda url,headers,limit:archive)
  return resolve,calls

 def test_shader_and_resource_pack_are_excluded_from_server_mods(self):
  resolve,calls=self.fixture([100,544096,301],
    {100:(6,432),544096:(6552,432),301:(12,432)})
  result=resolve()
  self.assertEqual(1,len(result["children"]))
  self.assertEqual("mods/mod.jar",result["bundle"]["members"][0]["path"])
  self.assertEqual([{"project_id":"544096","class_id":6552},
                    {"project_id":"301","class_id":12}],
                   result["parent"]["provenance"]["skipped_client_members"])
  self.assertFalse(any("/mods/544096/files/" in url for url in calls))
  self.assertFalse(any("/mods/301/files/" in url for url in calls))
  self.assertEqual(1,len(normalize_bundle({"instance_id":"inst",
    "parent_content_id":"atm11",**result["bundle"]})["manifest"]["members"]))
 def test_unrecognized_server_content_remains_blocked(self):
  resolve,_=self.fixture([100,54321],{100:(6,432),54321:(17,432)})
  with self.assertRaisesRegex(MinecraftContentResolverError,
      "member 54321 uses unsupported class 17"):
   resolve()

 def test_spoofed_foreign_game_shader_remains_blocked(self):
  resolve,_=self.fixture([100,544096],
    {100:(6,432),544096:(6552,999)})
  with self.assertRaisesRegex(MinecraftContentResolverError,
      "member is not a Minecraft project"):
   resolve()

 def test_client_only_pack_is_not_silently_accepted(self):
  resolve,_=self.fixture([544096],{544096:(6552,432)})
  with self.assertRaisesRegex(MinecraftContentResolverError,
      "no required managed mods"):
   resolve()

 def test_preserves_installed_runtime_loader_compatibility_gate(self):
  resolve,_=self.fixture([100,544096],{100:(6,432),544096:(6552,432)})
  runtime={"loader":"neoforge","compatibility":{"embedded_mod_loaders":{
    "26.1.2":{"id":"neoforge","version":"26.1.2.99"}}}}
  with self.assertRaisesRegex(MinecraftContentResolverError,
      "modpack requires neoforge 26.1.2.11, but runtime provides 26.1.2.99"):
   resolve(runtime)
  runtime["compatibility"]["embedded_mod_loaders"]["26.1.2"]["version"]="26.1.2.11"
  self.assertEqual(1,len(resolve(runtime)["children"]))

if __name__=="__main__":
 unittest.main()
