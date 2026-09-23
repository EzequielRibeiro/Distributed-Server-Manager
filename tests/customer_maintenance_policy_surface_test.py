#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from customer_maintenance_workspace import _run_view


class CustomerMaintenancePolicySurfaceTest(unittest.TestCase):
 def test_run_view_does_not_expose_agent_or_command_ids(self):
  raw={'run_id':'r1','agent_id':'agent-secret','instance_id':'i1','due_at':'2026-09-16T15:00:00Z','status':'running','stage':'stopping','preflight_command_id':'cmd-pre','save_command_id':'cmd-save','stop_command_id':'cmd-stop','start_command_id':'cmd-start','readiness_command_id':'cmd-doctor','event':{'pending_work':[{'kind':'content-update','ref':'mod-a','available_version':'2','desired_revision':3,'status':'dispatched'}]},'warnings_sent':[300,60]}
  view=_run_view(raw);self.assertEqual(view['run_id'],'r1');self.assertEqual(view['pending_work'][0]['ref'],'mod-a')
  for key in ('agent_id','instance_id','preflight_command_id','save_command_id','stop_command_id','start_command_id','readiness_command_id'):self.assertNotIn(key,view)
 def test_service_enforces_customer_permissions_and_server_owned_contract(self):
  text=(ROOT/'dashboard/customer_maintenance_workspace.py').read_text(encoding='utf-8')
  self.assertIn('self.workspace.require(user,instance_id,"instance.restart")',text);self.assertIn('self.workspace.require(user,instance_id,"settings.write")',text)
  self.assertIn('unsupported maintenance policy fields',text);self.assertIn('normalize_policy(payload)',text);self.assertNotIn('agent_id',text.split('_POLICY_FIELDS=',1)[1].split('\n',1)[0])
 def test_http_is_customer_scoped_and_audited(self):
  text=(ROOT/'dashboard/customer_maintenance_http.py').read_text(encoding='utf-8')
  self.assertIn('PATH="/api/customer/instance/workspace/maintenance"',text);self.assertIn('session_user_from_headers',text);self.assertIn('MAINTENANCE_POLICY_UPDATED',text);self.assertNotIn('command_id',text)
 def test_ui_is_safe_and_capability_driven(self):
  text=(ROOT/'dashboard/web/customer-maintenance.js').read_text(encoding='utf-8')
  self.assertIn('/api/customer/instance/workspace/maintenance',text);self.assertIn('native_countdown',text);self.assertIn('coalesce_updates',text);self.assertIn('settings.write', (ROOT/'dashboard/customer_maintenance_workspace.py').read_text(encoding='utf-8'))
  self.assertIn('Intl.supportedValuesOf("timeZone")',text);self.assertIn('mode==="fixed"',text);self.assertIn('offset<intervalSeconds',text);self.assertIn('syncWarnings()',text)
  self.assertNotIn('createElement("input");timezone.id="maintenance-timezone"',text)
  self.assertNotIn('innerHTML',text);self.assertNotIn('eval(',text);self.assertNotIn('shell',text.lower())
 def test_composition_and_static_policy_are_wired(self):
  part=(ROOT/'dashboard/server_part20.py').read_text(encoding='utf-8');service=(ROOT/'systemd/dsm-dashboard.service').read_text(encoding='utf-8');assets=(ROOT/'dashboard/static_asset_policy.py').read_text(encoding='utf-8');loader=(ROOT/'dashboard/web/customer-content-update-policy.js').read_text(encoding='utf-8')
  self.assertIn('install_customer_maintenance_http',part);self.assertIn('server_part20.py',service);self.assertIn('/customer-maintenance.js',assets);self.assertIn('/customer-maintenance.js',loader)


if __name__=='__main__':unittest.main()
