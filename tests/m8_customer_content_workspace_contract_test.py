#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
DASHBOARD=ROOT/"dashboard"
if str(DASHBOARD) not in sys.path:sys.path.insert(0,str(DASHBOARD))

from customer_content_workspace import CustomerContentWorkspaceService


class _Content:
 def __init__(self,item=None):self.item=dict(item or {})
 def get(self,instance_id,content_id):return dict(self.item) if self.item else None
 def customer_view(self,instance_id,limit=2000):return [dict(self.item)] if self.item else []
 def previous_revision(self,instance_id,content_id):return None
 def bundle_history(self,instance_id,content_id):return []


class _Workspace:
 root=ROOT
 def require(self,user,instance_id,permission):return {"id":instance_id,"game_id":"minecraft","runtime_id":"minecraft.java.paper","game_version":"1.21.1"}
 class repo:
  @staticmethod
  def workspace_policy(instance_id):return {}
 def _contract_policy(self,context,policy):
  class Policy:
   workshop_allowed=True;plugins_allowed=True;modpacks_allowed=True;datapacks_allowed=True;mods_allowed=True;modifications_allowed=True
  return {"providers":{"plugin":["modrinth","github","http"]}},Policy()


class M8CustomerContentWorkspaceContractTest(unittest.TestCase):
 def service(self,item=None):
  service=CustomerContentWorkspaceService.__new__(CustomerContentWorkspaceService)
  service.workspace=_Workspace();service.content=_Content(item);return service

 def test_list_projects_provider_capabilities_and_update_gate(self):
  item={"instance_id":"i1","content_id":"p1","content_type":"plugin","provider":"github","revision":1}
  result=self.service(item).list({"username":"customer"},"i1")
  self.assertEqual(len(result),1)
  self.assertFalse(result[0]["update"]["supported"])
  self.assertTrue(result[0]["provider_capabilities"]["install"])
  self.assertFalse(result[0]["provider_capabilities"]["update"])

 def test_github_update_is_rejected_before_provider_dispatch(self):
  item={"instance_id":"i1","content_id":"p1","content_type":"plugin","provider":"github","revision":1,"desired_state":"installed","activation_state":"enabled","activation_order":0}
  with self.assertRaisesRegex(ValueError,"automatic content update is unavailable"):
   self.service(item).mutate({"username":"customer"},"i1","p1","update",{})

 def test_unknown_provider_install_is_fail_closed(self):
  service=self.service()
  with self.assertRaisesRegex(PermissionError,"content provider install is unavailable"):
   service.install({"username":"customer"},"i1",{"content_id":"x","content_type":"plugin","provider":"unknown","artifact":{"provider":"unknown","package_id":"x"}})

 def test_non_discoverable_provider_search_is_fail_closed(self):
  with self.assertRaisesRegex(PermissionError,"content provider discovery is unavailable"):
   self.service().search({"username":"customer"},"i1","github","plugin","project")


if __name__=="__main__":unittest.main()
