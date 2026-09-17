#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DASHBOARD=ROOT/"dashboard"
if str(DASHBOARD) not in sys.path:sys.path.insert(0,str(DASHBOARD))

from content_provider_capabilities import (
 ContentProviderCapabilityError,
 customer_managed_providers,
 load_provider_capabilities,
 normalize_provider,
 provider_capabilities,
 provider_supports,
)


class M8ContentProviderCapabilitiesTest(unittest.TestCase):
 def test_manifest_is_explicit_and_complete_for_current_provider_surface(self):
  matrix=load_provider_capabilities(ROOT)
  self.assertEqual(set(matrix["providers"]),{"steam-workshop","modrinth","curseforge","github","http","http-archive","external-upload"})
  self.assertEqual(matrix["aliases"],{"steam":"steam-workshop"})
  for provider,entry in matrix["providers"].items():
   for key in ("customer_managed","discover","install","update","external_upload"):
    self.assertIs(type(entry[key]),bool,(provider,key))

 def test_only_server_authoritative_providers_advertise_update(self):
  matrix=load_provider_capabilities(ROOT)
  supported={provider for provider,entry in matrix["providers"].items() if entry["update"]}
  self.assertEqual(supported,{"steam-workshop","modrinth","curseforge"})
  for provider in supported:self.assertEqual(matrix["providers"][provider]["update_mode"],"server-authoritative")
  for provider in {"github","http","http-archive","external-upload"}:
   self.assertFalse(provider_supports(provider,"update",ROOT),provider)
   self.assertEqual(provider_capabilities(provider,ROOT)["update_mode"],"unsupported")

 def test_github_and_http_remain_install_only_until_resolver_exists(self):
  for provider in ("github","http","http-archive"):
   self.assertTrue(provider_supports(provider,"customer_managed",ROOT),provider)
   self.assertTrue(provider_supports(provider,"install",ROOT),provider)
   self.assertFalse(provider_supports(provider,"discover",ROOT),provider)
   self.assertFalse(provider_supports(provider,"update",ROOT),provider)

 def test_external_upload_is_a_separate_quarantined_surface(self):
  capabilities=provider_capabilities("external-upload",ROOT)
  self.assertTrue(capabilities["external_upload"])
  self.assertFalse(capabilities["customer_managed"])
  self.assertFalse(capabilities["install"])
  self.assertFalse(capabilities["update"])

 def test_steam_alias_preserves_workshop_compatibility(self):
  self.assertEqual(normalize_provider("steam",ROOT),"steam-workshop")
  self.assertTrue(provider_supports("steam","update",ROOT))
  self.assertIn("steam",customer_managed_providers(ROOT))
  self.assertIn("steam-workshop",customer_managed_providers(ROOT))

 def test_unknown_provider_and_action_fail_closed(self):
  self.assertEqual(provider_capabilities("unknown-provider",ROOT)["update"],False)
  self.assertFalse(provider_supports("unknown-provider","install",ROOT))
  self.assertFalse(provider_supports("modrinth","raw-shell",ROOT))

 def test_invalid_matrix_fails_closed(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);path=root/"catalog"/"v2"/"content-provider-capabilities.json";path.parent.mkdir(parents=True)
   path.write_text(json.dumps({"schema_version":1,"kind":"ContentProviderCapabilityMatrix","actions":[],"providers":{},"aliases":{}}),encoding="utf-8")
   with self.assertRaises(ContentProviderCapabilityError):load_provider_capabilities(root)
   self.assertFalse(provider_supports("modrinth","update",root))

 def test_workspace_uses_canonical_provider_capabilities(self):
  text=(DASHBOARD/"customer_content_workspace.py").read_text(encoding="utf-8")
  self.assertIn('provider_supports(provider,"customer_managed",self.workspace.root)',text)
  self.assertIn('provider_supports(provider,"discover",self.workspace.root)',text)
  self.assertIn('provider_supports(provider,"install",self.workspace.root)',text)
  self.assertIn('provider_supports(provider,"update",self.workspace.root)',text)
  self.assertIn('item["provider_capabilities"]=provider_capabilities(provider,self.workspace.root)',text)
  self.assertNotIn('_CUSTOMER_PROVIDERS=',text)

 def test_resources_are_not_advertised_without_runtime_projection_contract(self):
  declarations=[]
  for path in sorted((ROOT/"catalog"/"v2"/"games").glob("*/runtimes/*.json")):
   value=json.loads(path.read_text(encoding="utf-8"));content=value.get("content") or {};managed=content.get("managed") or {};types=managed.get("types") or {}
   if "resource" not in types:continue
   declaration=types["resource"]
   self.assertIsInstance(declaration,dict,path)
   self.assertTrue(str(managed.get("adapter") or "").strip(),path)
   self.assertTrue(str(declaration.get("directory") or "").strip(),path)
   self.assertIsInstance(declaration.get("providers"),list,path)
   self.assertTrue(declaration["providers"],path)
   declarations.append(path)
  self.assertEqual(declarations,[],"M8 must not advertise Resources until a runtime-specific projection is intentionally added and tested")


if __name__=="__main__":unittest.main()
