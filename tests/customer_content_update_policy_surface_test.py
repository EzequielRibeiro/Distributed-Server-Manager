#!/usr/bin/env python3
from __future__ import annotations
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class CustomerContentUpdatePolicySurfaceTest(unittest.TestCase):
 def test_customer_routes_are_instance_scoped_and_permission_gated(self):
  text=(ROOT/'dashboard/customer_content_http.py').read_text(encoding='utf-8')
  self.assertIn('UPDATE_POLICY=PATH+"/update-policy"',text)
  self.assertIn('UPDATE_POLICY_ITEM=UPDATE_POLICY+"/item"',text)
  self.assertIn('policy_api(user,instance_id,"content.install")',text)
  self.assertIn('api.workspace.require(user,instance_id,"settings.write")',text)
  self.assertIn('repo.set_content_policy(instance_id=instance_id,content_id=content_id,mode=body.get("mode")',text)
  self.assertIn('instance_update_policy_view(instance_id,backend=backend())',text)
  self.assertNotIn('selection_json',text)
 def test_customer_global_policy_uses_canonical_runtime_selection(self):
  text=(ROOT/'dashboard/server_update_api.py').read_text(encoding='utf-8')
  self.assertIn('def set_instance_update_policy(',text)
  self.assertIn("prepare_runtime_selection(root,runtime_id,'current')",text)
  self.assertIn('_require_runtime_prerequisites',text)
  self.assertIn('_PUBLIC_POLICY_FIELDS',text)
  self.assertIn('normalize_policy({})',text)
  self.assertIn("requested_by=str(requested_by or 'system')",text)
 def test_customer_ui_exposes_global_and_per_content_policy_without_unsafe_html(self):
  ui=(ROOT/'dashboard/web/customer-content-update-policy.js').read_text(encoding='utf-8')
  html=(ROOT/'dashboard/web/customer-instance.html').read_text(encoding='utf-8')
  static=(ROOT/'dashboard/static_asset_policy.py').read_text(encoding='utf-8')
  for mode in ('inherit','manual','automatic','maintenance','disabled'):self.assertIn(mode,ui)
  self.assertIn('contentEndpoint=`${workspace}/content`',ui)
  self.assertIn('endpoint=`${contentEndpoint}/update-policy`',ui)
  self.assertIn('content.install',ui);self.assertIn('settings.write',ui)
  self.assertIn('desired_state||"installed")!=="absent"',ui)
  self.assertIn('Backup antes da atualização do jogo',ui)
  self.assertIn('rollback transacional U9',ui)
  self.assertNotIn('innerHTML',ui)
  self.assertIn('<script src="/customer-content-update-policy.js"></script>',html)
  self.assertIn('"/customer-content-update-policy.js"',static)
  composition=(ROOT/'dashboard/server_part20.py').read_text(encoding='utf-8')
  self.assertIn('"/customer-content-update-policy.js":legacy.WEB_DIR/"customer-content-update-policy.js"',composition)
 def test_customer_ui_never_accepts_provider_or_version_for_policy_writes(self):
  ui=(ROOT/'dashboard/web/customer-content-update-policy.js').read_text(encoding='utf-8')
  self.assertIn('JSON.stringify({instance_id:iid,policy})',ui)
  self.assertIn('JSON.stringify({instance_id:iid,content_id:contentId,mode})',ui)
  self.assertNotIn('download_url',ui)
  self.assertNotIn('package_id',ui)


if __name__=='__main__':unittest.main()
