#!/usr/bin/env python3
from __future__ import annotations
import hashlib,io,json,sys,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"dashboard",ROOT/"database",ROOT/"core"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from customer_content_upload_service import CustomerContentUploadService

class _Workspace:
 def __init__(self,policy=None):
  self.policy=policy or SimpleNamespace(external_upload_allowed=True,modifications_allowed=True,mods_allowed=True,plugins_allowed=True,modpacks_allowed=True,datapacks_allowed=True)
  self.calls=[];self.repo=SimpleNamespace(workspace_policy=lambda iid:{})
 def require(self,user,iid,permission):self.calls.append((iid,permission));return {"id":iid,"agent_id":"agent-1","customer_id":7,"game_id":"minecraft","runtime_id":"minecraft.java.fabric","game_version":"1.21.1"}
 def _contract_policy(self,context,policy):return {},self.policy

class _Transfers:
 def __init__(self,status="staging"):
  self.created=[];self.staged=[];self.rejected=[];self.artifact_path=None;self.item={"transfer_id":"transfer-1","instance_id":"i1","agent_id":"agent-1","direction":"controller_to_agent","purpose":"content_upload","filename":"mod.zip","status":status,"sha256":"a"*64,"size_bytes":3,"destination_ref":"quarantine/i1/transfer-1/mod.zip" if status=="completed" else None}
 def create(self,**kw):self.created.append(kw);return dict(self.item)
 def get(self,tid):return dict(self.item)
 def stage_from_controller(self,tid,source,length):self.staged.append((tid,length,source.read()));self.item["status"]="queued";self.item["size_bytes"]=length;return dict(self.item)
 def controller_artifact(self,tid):
  if not self.artifact_path:raise FileNotFoundError(tid)
  return Path(self.artifact_path),dict(self.item)
 def cancel(self,tid):
  self.item["status"]="cancelled";return dict(self.item)
 def reject_content_upload(self,tid,reason):
  self.rejected.append((tid,str(reason)));self.item["status"]="failed";self.item["last_error"]=str(reason);return dict(self.item)

class _Content:
 def __init__(self):self.puts=[];self.bundles=[]
 def put(self,payload,requested_by=None):self.puts.append((dict(payload),requested_by));return {"changed":True,"assignment":dict(payload,revision=1)}
 def put_bundle(self,parent,bundle,children,requested_by=None):self.bundles.append((dict(parent),dict(bundle),[dict(x) for x in children],requested_by));return {"changed":True,"assignment":dict(parent,revision=1),"children":children}

def service(policy=None,status="staging"):
 s=CustomerContentUploadService.__new__(CustomerContentUploadService);s.backend=None;s.root=ROOT;s.workspace=_Workspace(policy);s.transfers=_Transfers(status);s.content=_Content();return s

class ExternalUploadTest(unittest.TestCase):
 def test_create_requires_content_install_and_uses_transfer_plane(self):
  s=service();item=s.create({"username":"alice"},"i1","mod.zip")
  self.assertEqual(s.workspace.calls[-1],("i1","content.install"));created=s.transfers.created[-1]
  self.assertEqual(created["purpose"],"content_upload");self.assertEqual(created["direction"],"controller_to_agent");self.assertEqual(created["agent_id"],"agent-1");self.assertEqual(item["transfer_id"],"transfer-1")
 def test_policy_blocks_external_upload(self):
  p=SimpleNamespace(external_upload_allowed=False,modifications_allowed=True,mods_allowed=True,plugins_allowed=True,modpacks_allowed=True,datapacks_allowed=True)
  with self.assertRaises(PermissionError):service(p).create({"username":"alice"},"i1","mod.zip")
 def test_stage_streams_through_artifact_repository(self):
  s=service();s.stage({"username":"alice"},"transfer-1",io.BytesIO(b"abc"),3);self.assertEqual(s.transfers.staged[-1],("transfer-1",3,b"abc"))
 def test_cancel_marks_transfer_cancelled(self):
  s=service(status="queued");item=s.cancel({"username":"alice"},"transfer-1");self.assertEqual(item["status"],"cancelled")

 def test_finalize_requires_agent_completion(self):
  with self.assertRaises(ValueError):service(status="staging").finalize({"username":"alice"},"transfer-1",{"content_id":"m1","content_type":"mod"})
 def test_finalize_rejection_marks_transfer_failed_for_cleanup(self):
  s=service(status="completed")
  with self.assertRaisesRegex(ValueError,"Identificador inválido"):s.finalize({"username":"alice"},"transfer-1",{"content_id":"All The Mods 11","content_type":"modpack"})
  self.assertEqual(s.transfers.item["status"],"failed");self.assertEqual(s.transfers.rejected[-1][0],"transfer-1");self.assertIn("Identificador inválido",s.transfers.rejected[-1][1])

 def test_finalize_injects_local_provider_and_safe_provenance(self):
  s=service(status="completed");result=s.finalize({"username":"alice"},"transfer-1",{"content_id":"m1","content_type":"mod","activation_state":"enabled"});payload,actor=s.content.puts[-1]
  self.assertEqual(actor,"alice");self.assertEqual(payload["provider"],"local");self.assertEqual(payload["target"],"external/m1");self.assertEqual(payload["artifact"]["package_id"],"quarantine/i1/transfer-1/mod.zip");self.assertEqual(payload["artifact"]["sha256"],"a"*64);self.assertTrue(payload["artifact"]["archive"]);self.assertEqual(payload["provenance"]["kind"],"customer-upload");self.assertTrue(payload["provenance"]["agent_validated"]);self.assertEqual(result["assignment"]["content_id"],"m1")
 def test_finalize_rejects_provider_artifact_and_workshop_spoofing(self):
  s=service(status="completed")
  for body in ({"content_id":"m1","content_type":"mod","provider":"http"},{"content_id":"m1","content_type":"mod","artifact":{"path":"/etc/passwd"}},{"content_id":"m1","content_type":"mod","target":"../../escape"},{"content_id":"m1","content_type":"workshop"}):
   with self.subTest(body=body),self.assertRaises(ValueError):s.finalize({"username":"alice"},"transfer-1",body)
 def test_finalize_preserves_minecraft_jar_as_file(self):
  s=service(status="completed");s.transfers.item["filename"]="plugin.jar";s.transfers.item["destination_ref"]="quarantine/i1/transfer-1/plugin.jar"
  s.finalize({"username":"alice"},"transfer-1",{"content_id":"plugin-1","content_type":"plugin"});payload,_=s.content.puts[-1]
  self.assertFalse(payload["artifact"]["archive"]);self.assertEqual(payload["artifact"]["package_id"],"quarantine/i1/transfer-1/plugin.jar")
 def test_finalize_requires_agent_quarantine_ack(self):
  s=service(status="completed");s.transfers.item["destination_ref"]="content-uploads/i1/transfer-1/mod.zip"
  with self.assertRaises(ValueError):s.finalize({"username":"alice"},"transfer-1",{"content_id":"m1","content_type":"mod"})

 def test_mrpack_upload_imports_composed_bundle_without_curseforge_key(self):
  child=b"jar";sha512=hashlib.sha512(child).hexdigest();sha1=hashlib.sha1(child).hexdigest()
  index={"formatVersion":1,"game":"minecraft","versionId":"pack-v1","name":"Imported Pack","dependencies":{"minecraft":"1.21.1","fabric-loader":"0.16.10"},"files":[{"path":"mods/example.jar","hashes":{"sha512":sha512,"sha1":sha1},"downloads":["https://cdn.modrinth.com/data/x/example.jar"],"fileSize":len(child),"env":{"server":"required","client":"required"}}]}
  out=io.BytesIO()
  with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as archive:
   archive.writestr("modrinth.index.json",json.dumps(index));archive.writestr("overrides/config/test.toml","x=1")
  with tempfile.NamedTemporaryFile(suffix=".mrpack",delete=False) as handle:
   handle.write(out.getvalue());path=handle.name
  try:
   s=service(status="completed");s.transfers.artifact_path=path;s.transfers.item["filename"]="pack.mrpack";s.transfers.item["destination_ref"]="quarantine/i1/transfer-1/pack.mrpack";s.transfers.item["sha256"]=hashlib.sha256(out.getvalue()).hexdigest()
   result=s.finalize({"username":"alice"},"transfer-1",{"content_id":"pack-1","content_type":"modpack"})
   parent,bundle,children,actor=s.content.bundles[-1]
   self.assertEqual(actor,"alice");self.assertEqual(parent["provider"],"modrinth");self.assertEqual(bundle["manifest_kind"],"mrpack-v1");self.assertEqual(bundle["loader_id"],"fabric");self.assertEqual(len(children),1);self.assertEqual(children[0]["provider"],"modrinth");self.assertEqual(result["assignment"]["content_id"],"pack-1")
  finally:
   Path(path).unlink(missing_ok=True)

 def test_curseforge_export_is_detected_and_explained_without_api_key(self):
  manifest={"manifestType":"minecraftModpack","manifestVersion":1,"minecraft":{"version":"1.21.1"},"files":[{"projectID":1,"fileID":2,"required":True}]}
  out=io.BytesIO()
  with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as archive:archive.writestr("manifest.json",json.dumps(manifest))
  with tempfile.NamedTemporaryFile(suffix=".zip",delete=False) as handle:
   handle.write(out.getvalue());path=handle.name
  try:
   s=service(status="completed");s.transfers.artifact_path=path;s.transfers.item["filename"]="curseforge.zip";s.transfers.item["destination_ref"]="quarantine/i1/transfer-1/curseforge.zip"
   with self.assertRaisesRegex(ValueError,"3rd Party API Key"):s.finalize({"username":"alice"},"transfer-1",{"content_id":"pack-cf","content_type":"modpack"})
  finally:
   Path(path).unlink(missing_ok=True)

 def test_mod_and_plugin_capabilities_are_enforced(self):
  p=SimpleNamespace(external_upload_allowed=True,modifications_allowed=True,mods_allowed=False,plugins_allowed=False,modpacks_allowed=False,datapacks_allowed=False)
  for ctype in ("mod","modpack","map","plugin"):
   with self.subTest(ctype=ctype),self.assertRaises(PermissionError):service(p,status="completed").finalize({"username":"alice"},"transfer-1",{"content_id":"x","content_type":ctype})

if __name__=="__main__":unittest.main()
