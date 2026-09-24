#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from customer_content_workspace import CustomerContentWorkspaceService

class _Workspace:
 def __init__(self,policy,context=None):self.policy=policy;self.calls=[];self.repo=SimpleNamespace(workspace_policy=lambda iid:{});self.root=ROOT;self.context=context or {"id":"i1","game_id":"dayz","agent_id":"agent-1"}
 def require(self,user,iid,permission):self.calls.append((iid,permission));return {**self.context,"id":iid}
 def _contract_policy(self,context,policy):return {},self.policy

class _Content:
 def __init__(self,current=None):self.current=current;self.puts=[];self.bundles=[];self.bundle_states=[];self.rollbacks=[];self.bundle_rollbacks=[]
 def list(self,**kw):return [{"content_id":"a"}]
 def customer_view(self,iid,limit=2000):return [{"content_id":"a"}]
 def previous_revision(self,iid,cid):return None
 def bundle_history(self,iid,cid):return []
 def rollback(self,iid,cid,revision=None,**kwargs):self.rollbacks.append((iid,cid,revision,kwargs));return {"changed":True}
 def rollback_bundle(self,iid,cid,revision=None,**kwargs):self.bundle_rollbacks.append((iid,cid,revision,kwargs));return {"changed":True}
 def bundle_diff(self,iid,cid,bundle):return {"added":[],"removed":[],"updated":[],"unchanged":[]}
 def get(self,iid,cid):return dict(self.current) if self.current else None
 def put(self,payload,requested_by=None):self.puts.append((dict(payload),requested_by));return {"changed":True,"assignment":{**payload,"revision":2}}
 def put_bundle(self,parent,bundle,children,requested_by=None):self.bundles.append((dict(parent),dict(bundle),[dict(x) for x in children],requested_by));return {"changed":True,"assignment":dict(parent),"children":children}
 def set_bundle_state(self,iid,cid,**kwargs):self.bundle_states.append((iid,cid,dict(kwargs)));return {"changed":True}

def _service(policy,current=None,context=None):
 service=CustomerContentWorkspaceService.__new__(CustomerContentWorkspaceService);service.workspace=_Workspace(policy,context);service.content=_Content(current);return service

def _policy(**overrides):
 values={"modifications_allowed":True,"mods_allowed":True,"plugins_allowed":True,"modpacks_allowed":True,"datapacks_allowed":True,"workshop_allowed":True,"external_upload_allowed":False,"custom_runtime_allowed":False};values.update(overrides);return SimpleNamespace(**values)

def _current():return {"content_id":"cf","content_type":"mod","desired_state":"installed","activation_state":"enabled","activation_order":5,"version":"1","provider":"http","target":"mods/cf","artifact":{"url":"https://example.invalid/cf.zip"},"provenance":{},"metadata":{},"dependencies":[],"conflicts":[]}

class CustomerContentWorkspaceTest(unittest.TestCase):
 def test_list_requires_content_read(self):
  service=_service(_policy());items=service.list({"username":"customer"},"i1");self.assertEqual(items[0]["content_id"],"a");self.assertFalse(items[0]["update"]["supported"]);self.assertEqual(service.workspace.calls,[('i1','content.read')])
 def test_customer_security_projection_hides_rule_and_file_details(self):
  service=_service(_policy())
  item={
   "content_id":"blocked",
   "effective_security_state":"blocked",
   "reconciliation":{
    "status":"security_blocked",
    "last_error":"YARA-X matched Capivara_EICAR_Test_File in payload/eicar.txt",
   },
  }
  projected=service._customer_security_projection(item)
  notice=projected["security_notice"]
  self.assertEqual(notice["state"],"blocked")
  self.assertIn("arquivo suspeito",notice["message"])
  self.assertIn("instalação foi cancelada",notice["message"])
  serialized=str(projected)
  self.assertNotIn("Capivara_EICAR_Test_File",serialized)
  self.assertNotIn("payload/eicar.txt",serialized)
 def test_install_uses_install_permission_and_forbids_server_owned_fields(self):
  service=_service(_policy())
  with self.assertRaises(PermissionError):service.install({"username":"u"},"i1",{"content_id":"x","provider":"http","agent_id":"spoof"})
  result=service.install({"username":"u"},"i1",{"content_id":"x","content_type":"mod","provider":"http","artifact":{"url":"https://example.invalid/x.zip"}})
  payload,requested_by=service.content.puts[-1];self.assertEqual(payload["instance_id"],"i1");self.assertEqual(payload["desired_state"],"installed");self.assertNotIn("agent_id",payload);self.assertNotIn("game_id",payload);self.assertEqual(requested_by,"u");self.assertTrue(result["changed"])
 def test_customer_cannot_select_agent_local_or_build_providers(self):
  for provider in ("local","custom","source-build"):
   with self.subTest(provider=provider),self.assertRaises(PermissionError):_service(_policy()).install({"username":"u"},"i1",{"content_id":"x","content_type":"mod","provider":provider})
 def test_contract_runtime_policy_is_enforced(self):
  with self.assertRaises(PermissionError):_service(_policy(mods_allowed=False)).install({"username":"u"},"i1",{"content_id":"x","content_type":"mod","provider":"http"})
  with self.assertRaises(PermissionError):_service(_policy(workshop_allowed=False)).install({"username":"u"},"i1",{"content_id":"x","content_type":"workshop","provider":"steam-workshop"})
 def test_customer_can_remove_local_external_upload_but_cannot_install_local_provider(self):
  current={**_current(),"content_id":"eicar","provider":"local","artifact":{"provider":"local","package_id":"quarantine/i1/t1/eicar.zip","ephemeral_upload":True},"target":"external/eicar"}
  service=_service(_policy(),current)
  with self.assertRaises(PermissionError):service.install({"username":"u"},"i1",{"content_id":"x","content_type":"mod","provider":"local"})
  result=service.mutate({"username":"u"},"i1","eicar","remove",{})
  payload,_=service.content.puts[-1]
  self.assertTrue(result["changed"])
  self.assertEqual(service.workspace.calls[-1],("i1","content.remove"))
  self.assertEqual(payload["provider"],"local")
  self.assertEqual(payload["desired_state"],"absent")
  self.assertEqual(payload["activation_state"],"disabled")

 def test_local_external_upload_removal_still_honors_contract_type_policy(self):
  current={**_current(),"content_id":"eicar","provider":"local","artifact":{"provider":"local","package_id":"quarantine/i1/t1/eicar.zip","ephemeral_upload":True},"target":"external/eicar"}
  with self.assertRaises(PermissionError):
   _service(_policy(mods_allowed=False),current).mutate({"username":"u"},"i1","eicar","remove",{})

 def test_remove_preserves_assignment_as_absent_and_disabled(self):
  service=_service(_policy(),_current());service.mutate({"username":"u"},"i1","cf","remove",{});payload,_=service.content.puts[-1];self.assertEqual(service.workspace.calls[-1],('i1','content.remove'));self.assertEqual(payload["desired_state"],"absent");self.assertEqual(payload["activation_state"],"disabled")
 def test_enable_disable_and_reorder_use_install_permission(self):
  for action,body,expected in (("disable",{},("activation_state","disabled")),("enable",{},("activation_state","enabled")),("reorder",{"activation_order":42},("activation_order",42))):
   with self.subTest(action=action):
    service=_service(_policy(),_current());service.mutate({"username":"u"},"i1","cf",action,body);payload,_=service.content.puts[-1];self.assertEqual(service.workspace.calls[-1],('i1','content.install'));self.assertEqual(payload[expected[0]],expected[1])
 def test_update_rejects_security_state_and_unknown_fields(self):
  service=_service(_policy(),_current())
  with self.assertRaises(PermissionError):service.mutate({"username":"u"},"i1","cf","update",{"security_state":"clean"})
  with self.assertRaises(ValueError):service.mutate({"username":"u"},"i1","cf","update",{"shell":"echo nope"})
 def test_structured_update_is_server_resolved_and_rollback_uses_history(self):
  context={"id":"i1","game_id":"minecraft","agent_id":"agent-1","runtime_id":"minecraft.java.fabric","game_version":"1.21.1"};current={**_current(),"provider":"modrinth","artifact":{"provider":"modrinth","package_id":"project:old","url":"https://cdn.modrinth.com/old.jar"},"provenance":{"minecraft_provider":{"project_id":"project","version_id":"old"}}};service=_service(_policy(),current,context);calls=[]
  service.minecraft_resolver=lambda provider,project,game_version,runtime,ctype:(calls.append((provider,project,game_version,ctype)) or {"version":"2","artifact":{"provider":"modrinth","package_id":"project:new","url":"https://cdn.modrinth.com/new.jar","filename":"new.jar","sha512":"a"*128},"provenance":{"project_id":"project","version_id":"new"},"metadata":{}})
  with patch('customer_content_workspace.runtime_definition',return_value={"loader":"fabric","content":{"managed":{"types":{"mod":{"providers":["modrinth"]}}}}}):service.mutate({"username":"u"},"i1","cf","update",{})
  payload,_=service.content.puts[-1];self.assertEqual(calls,[('modrinth','project','1.21.1','mod')]);self.assertEqual(payload["version"],"2");self.assertEqual(payload["artifact"]["package_id"],"project:new")
  with self.assertRaises(PermissionError):service.mutate({"username":"u"},"i1","cf","update",{"version":"client-picked"})
  service.mutate({"username":"u"},"i1","cf","rollback",{"revision":1});self.assertEqual(service.content.rollbacks[-1][2],1)
 def test_modpack_install_uses_composed_bundle_path_and_discards_customer_url(self):
  context={"id":"i1","game_id":"minecraft","agent_id":"agent-1","runtime_id":"minecraft.java.fabric","game_version":"1.21.1"};service=_service(_policy(),context=context)
  service.modpack_resolver=lambda provider,project,parent,version,runtime:{"parent":{"version":"Pack 1","artifact":{"provider":"modrinth","url":"https://cdn.modrinth.com/pack.mrpack","filename":"pack.mrpack","sha512":"a"*128,"archive":True},"provenance":{"project_id":"p","version_id":"v"}},"bundle":{"provider":"modrinth","provider_project_id":"p","provider_version_id":"v","minecraft_version":"1.21.1","loader_id":"fabric","loader_version":"0.16","manifest_kind":"mrpack-v1","members":[{"content_id":"mb-a","path":"mods/a.jar","required":True,"artifact":{"provider":"modrinth","url":"https://cdn.modrinth.com/a.jar","filename":"a.jar","sha512":"b"*128}}],"override_roots":["overrides"]},"children":[{"content_id":"mb-a","content_type":"mod","provider":"modrinth","version":"1","artifact":{"provider":"modrinth","url":"https://cdn.modrinth.com/a.jar","filename":"a.jar","sha512":"b"*128},"target":"mods/mb-a"}]}
  with patch('customer_content_workspace.runtime_definition',return_value={"loader":"fabric","content":{"bundles":{"modpack":{"providers":["modrinth","curseforge"]}}}}):result=service.install({"username":"u"},"i1",{"content_id":"pack","content_type":"modpack","provider":"modrinth","artifact":{"package_id":"project-slug","url":"https://evil.invalid/pack"}})
  parent,bundle_value,children,requested_by=service.content.bundles[-1];self.assertEqual(parent["artifact"]["url"],"https://cdn.modrinth.com/pack.mrpack");self.assertEqual(bundle_value["provider_version_id"],"v");self.assertEqual(children[0]["content_id"],"mb-a");self.assertEqual(requested_by,"u");self.assertTrue(result["changed"])
 def test_modpack_update_is_server_resolved_and_returns_manifest_diff(self):
  context={"id":"i1","game_id":"minecraft","agent_id":"agent-1","runtime_id":"minecraft.java.fabric","game_version":"1.21.1"};current={**_current(),"content_id":"pack","content_type":"modpack","provider":"modrinth","artifact":{"provider":"modrinth","package_id":"pack:new"},"provenance":{"minecraft_modpack":{"project_id":"pack-project","version_id":"old"}},"metadata":{"bundle":{"parent_content_id":"pack"},"minecraft_modpack":{"provider_project_id":"pack-project","provider_version_id":"old"}}};service=_service(_policy(),current,context);service.content.bundle_diff=lambda *args:{"added":["mb-new"],"removed":[],"updated":[],"unchanged":[]};service.content.bundle_history=lambda *args:[{"revision":2},{"revision":1}]
  service.modpack_resolver=lambda provider,project,parent,version,runtime:{"parent":{"version":"Pack 2","artifact":{"provider":"modrinth","url":"https://cdn.modrinth.com/pack2.mrpack","filename":"pack.mrpack","sha512":"a"*128,"archive":True},"provenance":{"project_id":"pack-project","version_id":"new"}},"bundle":{"provider":"modrinth","provider_project_id":"pack-project","provider_version_id":"new","minecraft_version":"1.21.1","loader_id":"fabric","loader_version":"0.16","manifest_kind":"mrpack-v1","members":[{"content_id":"mb-new","path":"mods/new.jar","required":True,"artifact":{"provider":"modrinth","url":"https://cdn.modrinth.com/new.jar","filename":"new.jar","sha512":"b"*128}}],"override_roots":["overrides"]},"children":[{"content_id":"mb-new","content_type":"mod","provider":"modrinth","version":"2","artifact":{"provider":"modrinth","url":"https://cdn.modrinth.com/new.jar","filename":"new.jar","sha512":"b"*128},"target":"mods/mb-new"}]}
  with patch('customer_content_workspace.runtime_definition',return_value={"loader":"fabric","content":{"bundles":{"modpack":{"providers":["modrinth"]}}}}):
   preview=service.mutate({"username":"u"},"i1","pack","preview-update",{})
   self.assertTrue(preview["preview"]);self.assertTrue(preview["changed"]);self.assertEqual(preview["manifest_diff"]["added"],["mb-new"]);self.assertEqual(preview["target"]["provider_version_id"],"new");self.assertEqual(service.content.bundles,[])
   result=service.mutate({"username":"u"},"i1","pack","update",{})
  self.assertEqual(service.content.bundles[-1][1]["provider_version_id"],"new");self.assertEqual(result["manifest_diff"]["added"],["mb-new"]);self.assertEqual(result["previous_bundle_revision"],2);self.assertEqual(service.content.bundles[-1][0]["provenance"]["update_checkpoint"]["previous_bundle_revision"],2)
  service.mutate({"username":"u"},"i1","pack","rollback",{"revision":1});self.assertEqual(service.content.bundle_rollbacks[-1][2],1)
 def test_modpack_lifecycle_propagates_and_generic_update_fails_closed(self):
  current={**_current(),"content_id":"pack","content_type":"modpack","provider":"modrinth","metadata":{"bundle":{"parent_content_id":"pack"}}};service=_service(_policy(),current)
  service.mutate({"username":"u"},"i1","pack","disable",{});self.assertEqual(service.content.bundle_states[-1][2]["activation_state"],"disabled")
  service.mutate({"username":"u"},"i1","pack","remove",{});self.assertEqual(service.content.bundle_states[-1][2]["desired_state"],"absent")
  with self.assertRaises(PermissionError):service.mutate({"username":"u"},"i1","pack","update",{"version":"2"})
 def test_prepare_clean_preserves_instance_and_skips_bundle_children(self):
  context={"id":"i1","game_id":"minecraft","agent_id":"agent-1","runtime_id":"minecraft.java.youer","game_version":"1.21.1"};service=_service(_policy(),context=context);removed=[]
  service.content.list=lambda **kwargs:[
   {"content_id":"pack","content_type":"modpack","desired_state":"installed","metadata":{}},
   {"content_id":"pack-child","content_type":"mod","desired_state":"installed","metadata":{"bundle":{"parent_content_id":"pack"}}},
   {"content_id":"extra-plugin","content_type":"plugin","desired_state":"installed","metadata":{}},
   {"content_id":"disabled-mod","content_type":"mod","desired_state":"absent","metadata":{}},
  ]
  service.mutate=lambda user,iid,cid,action,body:removed.append((cid,action)) or {"changed":True}
  result=service.prepare_clean_for_version_change({"username":"u"},"i1")
  self.assertEqual(removed,[("pack","remove"),("extra-plugin","remove")]);self.assertTrue(result["completed"]);self.assertIn("world",result["preserved"]);self.assertIn("ports",result["preserved"])

 def test_missing_assignment_is_not_found(self):
  with self.assertRaises(KeyError):_service(_policy()).mutate({"username":"u"},"i1","missing","disable",{})

if __name__=="__main__":unittest.main()
