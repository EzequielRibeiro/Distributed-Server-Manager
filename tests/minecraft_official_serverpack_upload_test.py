#!/usr/bin/env python3
"""Customer official Server Pack preview, provenance, bundle and safety gates."""
from __future__ import annotations
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from functools import partial
from unittest.mock import patch
from types import SimpleNamespace

from tests.universal_content_external_upload_test import service
from customer_serverpack_service import build_serverpack_bundle
from dashboard.customer_content_upload_service import CustomerContentUploadService
from core.content_bundle import ContentBundleValidationError,normalize_bundle

PROJECT=1148445
FILE=8916964
FILENAME="ServerFiles-0.9.0-beta.zip"
USER={"username":"alice"}
CONTEXT={"id":"i1","agent_id":"agent-1","customer_id":7,
         "game_id":"minecraft","runtime_id":"minecraft.java.neoforge",
         "game_version":"26.1.2","build_id":"26.1.2.109"}
METADATA={"display_name":"ATM11 0.9.0 beta","serverpack":{
 "format":"official-serverpack-v1","curseforge_project_id":str(PROJECT),
 "curseforge_file_id":str(FILE),"loader_version":"26.1.2.109",
 "expected_revision":0}}

def mock_api(path, *, flags=None, file_version_tags=None, project_id=PROJECT):
 sha1=hashlib.sha1(path.read_bytes()).hexdigest()
 calls=[]
 def requester(url,headers):
  calls.append(url)
  assert headers=={"x-api-key":"test-secret"}
  if "/categories?" in url:
   return {"data":[{"id":4471,"slug":"modpacks","name":"Modpacks","isClass":True}]}
  if url.endswith("/mods/"+str(project_id)):
   return {"data":{"id":project_id,"gameId":432,"classId":4471,
                   "name":"All the Mods 11","allowModDistribution":True}}
  if url.endswith(f"/mods/{project_id}/files/{FILE}"):
   return {"data":{"id":FILE,"fileName":FILENAME,"isAvailable":True,
                   "gameVersions":file_version_tags if file_version_tags is not None else ["26.1.2","NeoForge"],
                   "fileLength":path.stat().st_size,
                   "hashes":[{"algo":1,"value":(flags or {}).get("sha1",sha1)}]}}
  raise AssertionError(f"unexpected provider request: {url}")
 return requester,calls

def archive(path, *, version="26.1.2", build="26.1.2.109"):
 with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as pack:
  pack.writestr("settings.cfg",f"MCVER={version}\nMODLOADER=neoforge\nNEOFORGE_VERSION={build}\n")
  for name in ("a","b"):
   pack.writestr(f"mods/{name}.jar",f"jar-{name}".encode())
  pack.writestr("defaultconfigs/settings.cfg","test=true")
  pack.writestr("StartServer.sh","#!/bin/sh\necho DONT_EXECUTE\n")

class OfficialServerPackUploadTest(unittest.TestCase):
 def fixture(self,td):
  path=Path(td)/FILENAME
  archive(path)
  s=service(status="completed")
  s.workspace.require=lambda u,i,p:dict(CONTEXT)
  s.content.list=lambda **kwargs:[]
  s.transfers.artifact_path=path
  s.transfers.item.update({"filename":FILENAME,
    "destination_ref":f"quarantine/i1/transfer-1/{FILENAME}",
    "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
    "size_bytes":path.stat().st_size})
  requester,calls=mock_api(path)
  patcher=patch("customer_serverpack_service.runtime_definition",return_value={"loader":"neoforge"})
  return path,s,requester,calls,patcher

 def test_preview_is_readonly_and_finalize_puts_owned_hashed_local_bundle(self):
  with tempfile.TemporaryDirectory() as td:
   path,s,requester,calls,patcher=self.fixture(td)
   with patcher,patch("customer_content_upload_service.build_serverpack_bundle",
      partial(build_serverpack_bundle,requester=requester,load_secret=lambda path:"test-secret")):
    preview=s.preview_serverpack(USER,"transfer-1",
      {"content_id":"atm11","content_type":"modpack","metadata":METADATA})
    self.assertEqual(preview["mod_count"],2)
    self.assertEqual(preview["update_plan"]["operation"],"install")
    self.assertEqual(preview["update_plan"]["previous_revision"],0)
    self.assertEqual(preview["loader_version"],"26.1.2.109")
    self.assertTrue(preview["requires_stopped_instance"])
    self.assertFalse(preview["runs_pack_scripts"])
    self.assertIn("StartServer.sh",preview["ignored_launchers"])
    self.assertEqual([],s.content.bundles)
    result=s.finalize(USER,"transfer-1",{"content_id":"atm11",
      "content_type":"modpack","metadata":METADATA})
   parent,bundle,children,actor=s.content.bundles[-1]
   self.assertEqual(actor,"alice")
   self.assertEqual(parent["provider"],"local")
   self.assertEqual(bundle["manifest_kind"],"serverpack-local-v1")
   self.assertEqual(bundle["override_roots"],["server-overrides"])
   self.assertEqual(len(children),2)
   self.assertEqual({x["provider"] for x in children},{"local"})
   self.assertEqual({tuple(x["dependencies"]) for x in children},{("atm11",)})
   self.assertEqual(parent["artifact"]["sha256"],hashlib.sha256(path.read_bytes()).hexdigest())
   normalized=normalize_bundle({"instance_id":"i1","parent_content_id":"atm11",**bundle})
   self.assertEqual(len(normalized["manifest"]["members"]),2)
   self.assertTrue(all(x["artifact"]["serverpack_child_v1"] for x in children))
   self.assertEqual(result["revision_source"],"official-serverpack-upload")
   self.assertGreaterEqual(len(calls),4)

 def test_official_zip_without_manifest_auto_detects_neoforge_installer(self):
  with tempfile.TemporaryDirectory() as td:
   path,s,_,_,patcher=self.fixture(td)
   with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as server:
    server.writestr("neoforge-26.1.2.109-installer.jar",b"verified-installer")
    server.writestr("startserver.sh","NEOFORGE_VERSION=26.1.2.109\n")
    server.writestr("mods/example.jar",b"server-mod")
    server.writestr("config/options.toml",b"unchanged-config")
   s.transfers.item["sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
   s.transfers.item["size_bytes"]=path.stat().st_size
   requester,_=mock_api(path)
   automatic={"display_name":"ATM11","serverpack":{
    "format":"official-serverpack-v1",
    "curseforge_project_id":str(PROJECT),
    "curseforge_file_id":str(FILE),
   }}
   with patcher:
    preview,parent,bundle,children=build_serverpack_bundle(
       Path(td),CONTEXT,s.transfers.item,s.transfers.item["destination_ref"],
       "atm11",automatic,path,requester=requester,
       load_secret=lambda _: "test-secret")
   self.assertEqual(preview["loader_version"],"26.1.2.109")
   self.assertTrue(preview["loader_version_verified_in_zip"])
   self.assertFalse(preview["loader_version_manually_declared"])
   self.assertEqual(preview["mod_count"],1)
   self.assertEqual(bundle["loader_version"],"26.1.2.109")
   self.assertEqual(len(children),1)

 def test_official_sha1_mismatch_is_hard_rejection(self):
  with tempfile.TemporaryDirectory() as td:
   path,s,requester,_,patcher=self.fixture(td)
   requester,_=mock_api(path,flags={"sha1":"0"*40})
   with patcher,self.assertRaisesRegex(ValueError,"SHA-1"):
    build_serverpack_bundle(Path(td),CONTEXT,s.transfers.item,
      s.transfers.item["destination_ref"],"atm11",METADATA,path,
      requester=requester,load_secret=lambda path:"test-secret")
   self.assertFalse(s.content.bundles)

 def test_wrong_source_version_and_missing_version_proof_reject(self):
  with tempfile.TemporaryDirectory() as td:
   path,s,_,_,patcher=self.fixture(td)
   with patcher:
    for bad in ({"serverpack":{"format":"official-serverpack-v1",
                                "curseforge_project_id":"0","curseforge_file_id":str(FILE),
                                "loader_version":"26.1.2.109"}},
                {"serverpack":{"format":"official-serverpack-v1",
                                "curseforge_project_id":str(PROJECT),
                                "curseforge_file_id":str(FILE),"loader_version":"26.1.2.99"}}):
     with self.subTest(bad=bad),self.assertRaises((AssertionError,ValueError)):
      requester,_=mock_api(path)
      build_serverpack_bundle(Path(td),CONTEXT,s.transfers.item,
       s.transfers.item["destination_ref"],"atm11",bad,path,
       requester=requester,load_secret=lambda path:"test-secret")

 def test_bundle_cannot_impersonate_arbitrary_local_file(self):
  with self.assertRaises(ContentBundleValidationError):
   normalize_bundle({"instance_id":"i1","parent_content_id":"atm11",
     "provider":"local","provider_project_id":"cf-1148445",
     "provider_version_id":"file-8916964","minecraft_version":"26.1.2",
     "loader_id":"neoforge","loader_version":"26.1.2.109",
     "manifest_kind":"serverpack-local-v1","members":[{
       "content_id":"mb-test","path":"mods/a.jar","artifact":{
          "provider":"local","serverpack_child_v1":True,
          "ephemeral_upload":True,"bundle_parent_content_id":"atm11",
          "bundle_member":"mods/a.jar","sha256":"a"*64,
          "size_bytes":20,"url":"https://untrusted.invalid/override"}}]})

if __name__=="__main__":
 unittest.main()
