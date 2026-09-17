#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"dashboard",):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from content_action_capabilities import effective_content_actions

def policy(**values):
 base={"modifications_allowed":True,"mods_allowed":True,"plugins_allowed":True,"modpacks_allowed":True,"datapacks_allowed":True,"workshop_allowed":True};base.update(values);return SimpleNamespace(**base)

def actions(item,permissions={"content.install","content.remove"},providers=None,content_policy=None):
 capabilities={"providers":providers or {"plugin":["modrinth","github"],"mod":["modrinth","curseforge"],"modpack":["modrinth","curseforge"],"workshop":["steam-workshop"]}}
 return effective_content_actions(item=item,permissions=set(permissions),capabilities=capabilities,policy=content_policy or policy(),root=ROOT)

class M8ContentActionCapabilitiesTest(unittest.TestCase):
 def test_modrinth_plugin_projects_full_supported_actions(self):
  value=actions({"content_type":"plugin","provider":"modrinth","desired_state":"installed","activation_state":"enabled","update":{"supported":True,"rollback_available":True}})
  self.assertEqual(value,{"enable":False,"disable":True,"reorder":True,"update":True,"rollback":True,"remove":True})
 def test_disabled_item_projects_enable_not_disable(self):
  value=actions({"content_type":"plugin","provider":"modrinth","desired_state":"installed","activation_state":"disabled","update":{"supported":True,"rollback_available":False}})
  self.assertTrue(value["enable"]);self.assertFalse(value["disable"]);self.assertFalse(value["rollback"])
 def test_modpack_never_projects_reorder(self):
  value=actions({"content_type":"modpack","provider":"curseforge","desired_state":"installed","activation_state":"enabled","update":{"supported":True,"rollback_available":True}})
  self.assertFalse(value["reorder"]);self.assertTrue(value["update"]);self.assertTrue(value["rollback"])
 def test_install_only_provider_cannot_update(self):
  value=actions({"content_type":"plugin","provider":"github","desired_state":"installed","activation_state":"enabled","update":{"supported":False,"rollback_available":True}})
  self.assertFalse(value["update"]);self.assertTrue(value["rollback"])
 def test_provider_not_declared_by_runtime_cannot_update(self):
  value=actions({"content_type":"plugin","provider":"modrinth","desired_state":"installed","activation_state":"enabled","update":{"supported":True,"rollback_available":False}},providers={"plugin":["github"]})
  self.assertFalse(value["update"])
 def test_read_only_user_receives_no_mutation_actions(self):
  value=actions({"content_type":"plugin","provider":"modrinth","desired_state":"installed","activation_state":"enabled","update":{"supported":True,"rollback_available":True}},permissions={"content.read"})
  self.assertFalse(any(value.values()))
 def test_remove_permission_is_independent_from_install_permission(self):
  value=actions({"content_type":"plugin","provider":"modrinth","desired_state":"installed","activation_state":"enabled","update":{"supported":True,"rollback_available":True}},permissions={"content.remove"})
  self.assertTrue(value["remove"]);self.assertFalse(value["disable"]);self.assertFalse(value["update"])
 def test_disallowed_runtime_type_fails_closed(self):
  value=actions({"content_type":"plugin","provider":"modrinth","desired_state":"installed","activation_state":"enabled","update":{"supported":True,"rollback_available":True}},content_policy=policy(plugins_allowed=False))
  self.assertFalse(any(value.values()))
 def test_absent_item_has_no_actions(self):
  value=actions({"content_type":"plugin","provider":"modrinth","desired_state":"absent","activation_state":"disabled","update":{"supported":True,"rollback_available":True}})
  self.assertFalse(any(value.values()))

if __name__=="__main__":unittest.main()
