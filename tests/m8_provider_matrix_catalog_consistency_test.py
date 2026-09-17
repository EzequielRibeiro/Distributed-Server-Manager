#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DASHBOARD=ROOT/"dashboard"
if str(DASHBOARD) not in sys.path:sys.path.insert(0,str(DASHBOARD))

from content_provider_capabilities import load_provider_capabilities,normalize_provider


class M8ProviderMatrixCatalogConsistencyTest(unittest.TestCase):
 def test_every_runtime_managed_provider_exists_in_canonical_matrix(self):
  matrix=load_provider_capabilities(ROOT);known=set(matrix["providers"])
  checked=[]
  for path in sorted((ROOT/"catalog"/"v2"/"games").glob("*/runtimes/*.json")):
   value=json.loads(path.read_text(encoding="utf-8"));content=value.get("content") or {}
   workshop=(content.get("steam_workshop") or {}) if isinstance(content,dict) else {}
   if workshop:
    self.assertIn("steam-workshop",known,path);checked.append((path,"workshop","steam-workshop"))
   managed=(content.get("managed") or {}) if isinstance(content,dict) else {};types=(managed.get("types") or {}) if isinstance(managed,dict) else {}
   if isinstance(types,dict):
    for content_type,declaration in types.items():
     if not isinstance(declaration,dict):continue
     for provider in declaration.get("providers") or []:
      canonical=normalize_provider(provider,ROOT)
      self.assertIn(canonical,known,(path,content_type,provider));checked.append((path,content_type,canonical))
   bundles=(content.get("bundles") or {}) if isinstance(content,dict) else {}
   if isinstance(bundles,dict):
    for content_type,declaration in bundles.items():
     if not isinstance(declaration,dict):continue
     for provider in declaration.get("providers") or []:
      canonical=normalize_provider(provider,ROOT)
      self.assertIn(canonical,known,(path,content_type,provider));checked.append((path,content_type,canonical))
  self.assertTrue(checked,"expected at least one catalog content provider declaration")

 def test_provider_matrix_does_not_make_external_upload_a_catalog_resolver(self):
  matrix=load_provider_capabilities(ROOT)
  self.assertTrue(matrix["providers"]["external-upload"]["external_upload"])
  self.assertFalse(matrix["providers"]["external-upload"]["customer_managed"])
  for path in sorted((ROOT/"catalog"/"v2"/"games").glob("*/runtimes/*.json")):
   text=path.read_text(encoding="utf-8")
   self.assertNotIn('"external-upload"',text,path)


if __name__=="__main__":unittest.main()
