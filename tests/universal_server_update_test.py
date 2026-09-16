#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT/'core',ROOT/'database',ROOT/'dashboard',ROOT/'agents/linux/runtime'):
 if str(p) not in sys.path:sys.path.insert(0,str(p))
from server_update_platform import effective_content_update_mode,normalize_content_update_mode,normalize_policy,maintenance_window_open,should_apply,should_apply_content,ServerUpdateValidationError
from server_update_provider import parse_manifest_buildid,parse_app_info_buildid,detect_update
from server_update_schema import content_update_ddl,ensure_server_update_schema,server_update_ddl
from server_update_transaction import activate,prepare_staging,restore_files,rollback,snapshot_files

class UniversalServerUpdateTest(unittest.TestCase):
 def test_policy_modes_and_window(self):
  p=normalize_policy({'mode':'maintenance','timezone':'UTC','weekdays':[3],'start_time':'18:00','duration_minutes':90,'check_interval_seconds':900})
  self.assertTrue(maintenance_window_open(p,datetime(2026,9,3,18,30,tzinfo=timezone.utc)))
  self.assertTrue(should_apply(p,'update_available',now=datetime(2026,9,3,18,30,tzinfo=timezone.utc)))
  self.assertFalse(should_apply({'mode':'manual'},'update_available'));self.assertTrue(should_apply({'mode':'manual'},'update_available',manual=True))
  with self.assertRaises(ServerUpdateValidationError):normalize_policy({'mode':'automatic','timezone':'../bad'})
 def test_content_policy_inheritance_and_manual_override(self):
  base={'mode':'automatic','timezone':'UTC','weekdays':list(range(7)),'start_time':'04:00','duration_minutes':60,'check_interval_seconds':900}
  self.assertEqual(effective_content_update_mode(base,'inherit'),'automatic');self.assertEqual(effective_content_update_mode(base,'maintenance'),'maintenance')
  self.assertTrue(should_apply_content(base,'update_available',override='inherit'));self.assertFalse(should_apply_content(base,'update_available',override='manual'));self.assertFalse(should_apply_content(base,'update_available',override='disabled'))
  self.assertTrue(should_apply_content(base,'update_available',override='disabled',manual=True));self.assertFalse(should_apply_content(base,'up_to_date',override='automatic'))
  for mode in ('inherit','manual','automatic','maintenance','disabled'):self.assertEqual(normalize_content_update_mode(mode),mode)
  with self.assertRaises(ServerUpdateValidationError):normalize_content_update_mode('../../automatic')
 def test_content_maintenance_uses_instance_window(self):
  base={'mode':'manual','timezone':'UTC','weekdays':[3],'start_time':'18:00','duration_minutes':90,'check_interval_seconds':900}
  self.assertTrue(should_apply_content(base,'update_available',override='maintenance',now=datetime(2026,9,3,18,30,tzinfo=timezone.utc)))
  self.assertFalse(should_apply_content(base,'update_available',override='maintenance',now=datetime(2026,9,3,20,0,tzinfo=timezone.utc)))
 def test_steam_build_parsers(self):
  self.assertEqual(parse_manifest_buildid('"AppState" { "buildid" "12345" }'),'12345')
  text='''"branches"\n{\n "public"\n {\n  "buildid" "100"\n }\n "beta"\n {\n  "buildid" "200"\n }\n}'''
  self.assertEqual(parse_app_info_buildid(text,'public'),'100');self.assertEqual(parse_app_info_buildid(text,'beta'),'200')
 def test_detector_is_generic_across_steam_games(self):
  selections=[{'provider':'steam','install':{'package_id':'380870'},'game':'projectzomboid'},{'provider':'steam','install':{'package_id':'294420'},'game':'7daystodie'}]
  with patch('server_update_provider.installed_steam_build',return_value='100'),patch('server_update_provider.upstream_steam_build',return_value='101'):
   for selection in selections:
    detail=detect_update(selection,Path('/tmp/game'),'steamcmd');self.assertEqual(detail['state'],'update_available');self.assertTrue(detail['rollback_supported'])
 def test_non_steam_detector_fails_closed(self):
  detail=detect_update({'provider':'http'},Path('/tmp/game'));self.assertEqual(detail['state'],'unsupported');self.assertFalse(detail['detector_supported'])
 def test_transaction_restores_game_data_and_provider_metadata(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);target=root/'serverfiles';target.mkdir();(target/'server.bin').write_text('old',encoding='utf-8')
   manifest=root/'steamapps'/'appmanifest_123.acf';manifest.parent.mkdir();manifest.write_text('old-manifest',encoding='utf-8')
   created=root/'steamapps'/'new-created.acf';snapshot=snapshot_files([manifest,created]);staging=prepare_staging(target);(staging/'server.bin').write_text('new',encoding='utf-8')
   previous=activate(target,staging);self.assertEqual((target/'server.bin').read_text(),'new');manifest.write_text('new-manifest',encoding='utf-8');created.write_text('new',encoding='utf-8')
   self.assertTrue(rollback(target,previous));restore_files(snapshot);self.assertEqual((target/'server.bin').read_text(),'old');self.assertEqual(manifest.read_text(),'old-manifest');self.assertFalse(created.exists())
 def test_schema_parity(self):
  for backend in ('sqlite','postgresql','mysql','mariadb'):
   ddl=server_update_ddl(backend).lower();content=content_update_ddl(backend).lower()
   for table in ('instance_update_policy','instance_update_state','instance_update_runs'):self.assertIn('create table '+table,ddl)
   for table in ('content_update_policy','content_update_state'):self.assertIn('create table '+table,content)
   legacy='CREATE TABLE instance_update_policy (instance_id TEXT PRIMARY KEY);';compiled=ensure_server_update_schema(legacy,backend);self.assertIn('CREATE TABLE content_update_policy',compiled);self.assertEqual(compiled.count('CREATE TABLE content_update_policy'),1);self.assertEqual(ensure_server_update_schema(compiled,backend).count('CREATE TABLE content_update_policy'),1)
 def test_content_update_inventory_is_nonblocking_heartbeat_contract(self):
  linux=(ROOT/'agents/linux/runtime/agent.py').read_text();windows=(ROOT/'agents/windows/runtime/agent.py').read_text();heartbeat=(ROOT/'dashboard/agent_heartbeat_api.py').read_text();linux_inventory=(ROOT/'agents/linux/runtime/content_update_inventory.py').read_text();windows_inventory=(ROOT/'agents/windows/runtime/content_update_inventory.py').read_text()
  for agent in (linux,windows):
   self.assertIn('content_update_inventory()',agent);self.assertIn('start_content_update_inventory',agent)
   self.assertNotIn('refresh(config,force=True)',agent.replace(' ',''))
  for inventory in (linux_inventory,windows_inventory):
   self.assertIn('threading.Thread',inventory);self.assertIn('daemon=True',inventory);self.assertIn('def start_background',inventory)
  self.assertIn('record_content_update_inventory',heartbeat);self.assertIn('content_updates_accepted',heartbeat);self.assertIn('content_updates_rejected',heartbeat)
 def test_security_and_composition_contracts(self):
  api=(ROOT/'dashboard/server_update_api.py').read_text();http=(ROOT/'dashboard/server_update_http.py').read_text();repo=(ROOT/'database/server_update_repository.py').read_text();ui=(ROOT/'dashboard/web/server-updates.js').read_text();agent=(ROOT/'agents/linux/runtime/server_update_agent.py').read_text();provider=(ROOT/'agents/linux/runtime/server_update_provider.py').read_text();executor=(ROOT/'agents/linux/runtime/game_data_executor.py').read_text();transaction=(ROOT/'agents/linux/runtime/server_update_transaction.py').read_text();service=(ROOT/'systemd/dsm-dashboard.service').read_text()
  self.assertIn("str(user.get('role') or '').lower()!='admin'",api);self.assertIn('SELECT id,agent_id,runtime_id,game_id,status FROM instances',api);self.assertIn('prepare_runtime_selection',api);self.assertIn('configure_content_update_policy',api);self.assertIn('/api/server-updates/content-policy',http)
  self.assertIn('JOIN instances i ON i.id=a.instance_id',repo);self.assertIn("provider=_short(row['provider']",repo);self.assertIn("package=_short(artifact.get('package_id'))",repo)
  self.assertIn('textContent',ui);self.assertNotIn('innerHTML',ui)
  for text in (agent,provider,executor,transaction):self.assertNotIn('shell=True',text);self.assertNotIn('os.system(',text)
  self.assertIn('instance_runtime.lifecycle(config, current, "stop")',agent);self.assertIn('instance_runtime.doctor',agent);self.assertIn('create_backup',agent);self.assertIn('prepare_staging',agent);self.assertIn('rollback(target, previous)',agent)
  self.assertIn('os.replace(staging, target)',transaction);self.assertIn('os.replace(previous, target)',transaction);self.assertIn('argv.extend(["-beta",branch])',executor.replace(' ',''));self.assertIn('_server_update',executor);self.assertIn('server_part18.py',service)
 def test_baseline_compiler_includes_update_schema(self):
  text=(ROOT/'database/schema_baseline.py').read_text();self.assertIn('ensure_server_update_schema',text)
 def test_scheduler_hooks_existing_authenticated_game_data_transport(self):
  text=(ROOT/'database/agent_game_data_repository.py').read_text();self.assertIn('schedule_due_for_agent',text);self.assertIn('apply_game_data_result',text)

if __name__=='__main__':unittest.main()
