#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from customer_content_workspace import CustomerContentWorkspaceService

class _Workspace:
 def __init__(self,policy):self.policy=policy;self.calls=[];self.repo=SimpleNamespace(workspace_policy=lambda iid:{})
 def require(self,user,iid,permission):self.calls.append((iid,permission));return {"id":iid,"game_id":"dayz","agent_id":"agent-1"}
 def _contract_policy(self,context,policy):return {},self.policy

class _Content:
 def __init__(self,current=None):self.current=current;self.puts=[]
 def list(self,**kw):return [{"content_id":"a"}]
 def get(self,iid,cid):return dict(self.current) if self.current else None
 def put(self,payload,requested_by=None):self.puts.append((dict(payload),requested_by));return {"changed":True,"assignment":{**payload,"revision":2}}

def _service(policy,current=None):
 service=CustomerContentWorkspaceService.__new__(CustomerContentWorkspaceService);service.workspace=_Workspace(policy);service.content=_Content(current);return service

def _policy(**overrides):
 values={"modifications_allowed":True,"mods_allowed":True,"plugins_allowed":True,"workshop_allowed":True,"external_upload_allowed":False,"custom_runtime_allowed":False};values.update(overrides);return SimpleNamespace(**values)

def _current():return {"content_id":"cf","content_type":"mod","desired_state":"installed","activation_state":"enabled","activation_order":5,"version":"1","provider":"http","target":"mods/cf","artifact":{"url":"https://example.invalid/cf.zip"},"provenance":{},"metadata":{},"dependencies":[],"conflicts":[]}

class CustomerContentWorkspaceTest(unittest.TestCase):
 def test_list_requires_content_read(self):
  service=_service(_policy());self.assertEqual(service.list({"username":"customer"},"i1"),[{"content_id":"a"}]);self.assertEqual(service.workspace.calls,[('i1','content.read')])
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
 def test_remove_preserves_assignment_as_absent_and_disabled(self):
  service=_service(_policy(),_current());service.mutate({"username":"u"},"i1","cf","remove",{});payload,_=service.content.puts[-1];self.assertEqual(service.workspace.calls[-1],('i1','content.remove'));self.assertEqual(payload["desired_state"],"absent");self.assertEqual(payload["activation_state"],"disabled")
 def test_enable_disable_reorder_and_update_use_install_permission(self):
  for action,body,expected in (("disable",{},("activation_state","disabled")),("enable",{},("activation_state","enabled")),("reorder",{"activation_order":42},("activation_order",42)),("update",{"version":"2"},("version","2"))):
   with self.subTest(action=action):
    service=_service(_policy(),_current());service.mutate({"username":"u"},"i1","cf",action,body);payload,_=service.content.puts[-1];self.assertEqual(service.workspace.calls[-1],('i1','content.install'));self.assertEqual(payload[expected[0]],expected[1])
 def test_update_rejects_security_state_and_unknown_fields(self):
  service=_service(_policy(),_current())
  with self.assertRaises(PermissionError):service.mutate({"username":"u"},"i1","cf","update",{"security_state":"clean"})
  with self.assertRaises(ValueError):service.mutate({"username":"u"},"i1","cf","update",{"shell":"echo nope"})
 def test_missing_assignment_is_not_found(self):
  with self.assertRaises(KeyError):_service(_policy()).mutate({"username":"u"},"i1","missing","disable",{})

if __name__=="__main__":unittest.main()
