#!/usr/bin/env python3
from __future__ import annotations
import hashlib,io,json,sys,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/"core") not in sys.path:sys.path.insert(0,str(ROOT/"core"))
from content_bundle import normalize_bundle
from minecraft_modpack_resolver import _require_runtime_loader_compatibility,resolve_curseforge_modpack,resolve_modrinth_modpack
from minecraft_content_resolver import MinecraftContentResolverError

def zip_bytes(files):
 out=io.BytesIO()
 with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
  for name,data in files.items():z.writestr(name,data)
 return out.getvalue()

class MinecraftModpackResolverTest(unittest.TestCase):
 def test_modrinth_mrpack_resolves_server_mods_and_overrides(self):
  child=b"jar-one";sha512=hashlib.sha512(child).hexdigest();sha1=hashlib.sha1(child).hexdigest()
  index={"formatVersion":1,"game":"minecraft","versionId":"pack-v1","name":"Pack","dependencies":{"minecraft":"1.21.1","fabric-loader":"0.16.10"},"files":[{"path":"mods/example.jar","hashes":{"sha512":sha512,"sha1":sha1},"downloads":["https://cdn.modrinth.com/data/x/example.jar"],"fileSize":len(child),"env":{"client":"required","server":"required"}},{"path":"resourcepacks/client.zip","hashes":{"sha512":"1"*128,"sha1":"2"*40},"downloads":["https://cdn.modrinth.com/data/x/client.zip"],"env":{"client":"required","server":"unsupported"}}]}
  pack=zip_bytes({"modrinth.index.json":json.dumps(index),"overrides/config/a.toml":"x=1","server-overrides/server.properties":"motd=test"});pack512=hashlib.sha512(pack).hexdigest();pack1=hashlib.sha1(pack).hexdigest()
  def request(url,headers):
   if "/project/pack/version?" in url:return [{"id":"pack-v1","project_id":"pack-project","version_number":"1.0","version_type":"release","date_published":"2026-01-01","status":"listed","game_versions":["1.21.1"],"loaders":["fabric"],"files":[{"filename":"pack.mrpack","url":"https://cdn.modrinth.com/data/p/pack.mrpack","primary":True,"hashes":{"sha512":pack512,"sha1":pack1},"size":len(pack)}]}]
   if url.endswith("/project/pack"):return {"id":"pack-project","project_type":"modpack","status":"approved"}
   raise AssertionError(url)
  result=resolve_modrinth_modpack("pack","parent-pack","1.21.1",{"loader":"fabric"},requester=request,bytes_requester=lambda url,headers,limit:pack)
  self.assertEqual(result["bundle"]["loader_id"],"fabric");self.assertEqual(result["bundle"]["override_roots"],["overrides","server-overrides"]);self.assertEqual(len(result["children"]),1);self.assertEqual(result["children"][0]["content_type"],"mod")
  normalized=normalize_bundle({"instance_id":"inst","parent_content_id":"parent-pack",**result["bundle"]});self.assertEqual(normalized["manifest"]["members"][0]["path"],"mods/example.jar")
 def test_modrinth_required_non_mod_server_file_fails_closed(self):
  data=b"x";index={"formatVersion":1,"game":"minecraft","versionId":"v","dependencies":{"minecraft":"1.21.1","fabric-loader":"1"},"files":[{"path":"resourcepacks/server.zip","hashes":{"sha512":hashlib.sha512(data).hexdigest(),"sha1":hashlib.sha1(data).hexdigest()},"downloads":["https://cdn.modrinth.com/x"],"env":{"server":"required"}}]};pack=zip_bytes({"modrinth.index.json":json.dumps(index)});h512=hashlib.sha512(pack).hexdigest();h1=hashlib.sha1(pack).hexdigest()
  def request(url,headers):
   if url.endswith('/project/pack'):return {"id":"p","project_type":"modpack","status":"approved"}
   return [{"id":"v","project_id":"p","version_number":"1","version_type":"release","status":"listed","game_versions":["1.21.1"],"loaders":["fabric"],"files":[{"filename":"x.mrpack","url":"https://cdn.modrinth.com/x","primary":True,"hashes":{"sha512":h512,"sha1":h1}}]}]
  with self.assertRaises(MinecraftContentResolverError):resolve_modrinth_modpack("pack","parent","1.21.1",{"loader":"fabric"},requester=request,bytes_requester=lambda u,h,l:pack)
 def test_runtime_embedded_loader_must_match_modpack(self):
  runtime={"loader":"youer","compatibility":{"embedded_mod_loaders":{"26.2":{"id":"neoforge","version":"26.2.0.7-beta"}}}}
  with self.assertRaisesRegex(MinecraftContentResolverError,"modpack requires neoforge 26.2.0.75"):
   _require_runtime_loader_compatibility(runtime,"26.2","neoforge","26.2.0.75")
  _require_runtime_loader_compatibility(runtime,"26.2","neoforge","26.2.0.7-beta")

 def test_curseforge_zip_resolves_required_mods_without_leaking_key(self):
  manifest={"manifestType":"minecraftModpack","manifestVersion":1,"minecraft":{"version":"1.21.1","modLoaders":[{"id":"fabric-0.16.10","primary":True}]},"files":[{"projectID":100,"fileID":200,"required":True}],"overrides":"overrides"};pack=zip_bytes({"manifest.json":json.dumps(manifest),"overrides/config/test.toml":"x=1"});pack_sha1=hashlib.sha1(pack).hexdigest();seen=[]
  def request(url,headers):
   seen.append((url,dict(headers)))
   if "/categories?" in url:return {"data":[{"id":4471,"isClass":True,"slug":"modpacks","name":"Modpacks"},{"id":6,"isClass":True,"slug":"mods","name":"Mods"}]}
   if url.endswith("/mods/500"):return {"data":{"id":500,"gameId":432,"classId":4471}}
   if "/mods/500/files?" in url:return {"data":[{"id":501,"fileName":"pack.zip","displayName":"1.0","fileDate":"2026-01-01","releaseType":1,"isAvailable":True,"gameVersions":["1.21.1","Fabric"],"downloadUrl":"https://edge.forgecdn.net/pack.zip","hashes":[{"algo":1,"value":pack_sha1}],"fileLength":len(pack)}]}
   if url.endswith("/mods/100"):return {"data":{"id":100,"gameId":432,"classId":6}}
   if url.endswith("/mods/100/files/200"):return {"data":{"id":200,"fileName":"mod.jar","displayName":"Mod 1","isAvailable":True,"gameVersions":["1.21.1","Fabric"],"downloadUrl":"https://edge.forgecdn.net/mod.jar","hashes":[{"algo":1,"value":"a"*40}],"fileLength":123}}
   raise AssertionError(url)
  result=resolve_curseforge_modpack("500","pack","1.21.1",{"loader":"fabric"},api_key="secret-key",requester=request,bytes_requester=lambda u,h,l:pack)
  self.assertEqual(result["bundle"]["manifest_kind"],"curseforge-v1");self.assertEqual(result["bundle"]["override_roots"],["overrides"]);self.assertEqual(result["children"][0]["artifact"]["sha1"],"a"*40)
  self.assertTrue(all(headers.get("x-api-key")=="secret-key" for _,headers in seen));self.assertNotIn("secret-key",json.dumps(result))

if __name__=="__main__":unittest.main()
