#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,json,os,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/'agents/linux/runtime',ROOT/'dashboard',ROOT/'database',ROOT/'core',ROOT):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from instance_workspace_policy import INSTANCE_PERMISSIONS,PERMISSION_PRESETS,validate_server_settings
from catalog_controller_runtime_policy import default_policy,load_policy
from server_settings_runtime import materialize_server_settings,prepare_spec
from server_settings_surface import apply_runtime_dependencies,materialize_dynamic_values,normalize_dynamic_values,observed_surface
from catalog_runtime_policy import materialize_network_properties
import customer_instance_workspace_service as workspace_service
import game_runtime,instance_runtime

def runtime(runtime_id):
 for path in (ROOT/'catalog/v2/games').glob('*/runtimes/*.json'):
  value=json.loads(path.read_text(encoding='utf-8'))
  if value.get('id')==runtime_id:return value
 raise AssertionError(f'runtime not found: {runtime_id}')

def declaration(runtime_id):return runtime(runtime_id)['server_settings']

class ServerSettingsRuntimeTest(unittest.TestCase):
 def test_all_published_runtimes_declare_customer_settings(self):
  matrix=json.loads((ROOT/'catalog/v2/support-matrix.json').read_text(encoding='utf-8'))
  published={item['id'] for item in matrix['published_runtimes']}
  self.assertEqual(31,len(published))
  missing=[]
  for runtime_id in sorted(published):
   settings=runtime(runtime_id).get('server_settings') or {}
   if not isinstance(settings.get('fields'),dict) or not settings['fields']:missing.append(runtime_id)
  self.assertEqual([],missing)

 def test_permissions_and_contract_player_limit(self):
  self.assertIn('settings.read',INSTANCE_PERMISSIONS);self.assertIn('settings.write',INSTANCE_PERMISSIONS)
  self.assertIn('settings.read',PERMISSION_PRESETS['viewer']);self.assertNotIn('settings.write',PERMISSION_PRESETS['viewer'])
  self.assertIn('settings.write',PERMISSION_PRESETS['operator'])
  dayz=declaration('dayz.stable')
  self.assertEqual({'max_players':20},validate_server_settings({'max_players':20},dayz,player_limit=20))
  with self.assertRaises(ValueError):validate_server_settings({'max_players':21},dayz,player_limit=20)
  with self.assertRaises(PermissionError):validate_server_settings({'evil_flag':'x'},dayz,player_limit=20)
  with self.assertRaises(ValueError):validate_server_settings({'server_name':'bad\nname'},dayz)

 def test_catalog_binding_is_server_owned(self):
  dayz=runtime('dayz.stable');policy=default_policy(dayz)
  self.assertEqual(dayz['server_settings']['fields'].keys(),policy['server_settings']['fields'].keys())
  hostile=dict(dayz);hostile['server_settings']={'fields':{'escape':{'type':'string','binding':{'kind':'property','path':'../escape','key':'x'}}}}
  with self.assertRaises(ValueError):default_policy(hostile)
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);store=root/'config/catalog-runtime';store.mkdir(parents=True)
   (store/'dayz.stable.json').write_text(json.dumps({'server_settings':{}}),encoding='utf-8')
   loaded=load_policy(root,dayz)
   self.assertIn('server_name',loaded['server_settings']['fields'])

 def test_file_materializers_dayz_minecraft_palworld_json_ini(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   cases=[]
   dayz=root/'dayz';dayz.mkdir();dayz_cfg=dayz/'serverDZ.cfg'
   dayz_cfg.write_text('hostname = "Original";  // Server name\nmaxPlayers = 60; // Maximum players\nsteamQueryPort = 27016; // query\nhostname = "Duplicate";\nmaxPlayers = 32;\nsteamQueryPort = 24003;\n',encoding='utf-8')
   spec={'configuration_root':str(dayz),'arguments':[],'catalog_server_settings':declaration('dayz.stable')}
   prepared=prepare_spec(spec,{'server_name':'Capivara Test','max_players':24});self.assertEqual(['serverDZ.cfg'],materialize_server_settings(prepared))
   text=dayz_cfg.read_text();self.assertIn('hostname = "Capivara Test";',text);self.assertIn('maxPlayers = 24;',text);self.assertEqual(1,text.count('hostname ='));self.assertEqual(1,text.count('maxPlayers ='))
   prepared['catalog_network_properties']=[{'path':'serverDZ.cfg','key':'steamQueryPort','value':'24003','syntax':'semicolon'}];prepared['catalog_variables']={}
   self.assertEqual(['serverDZ.cfg'],materialize_network_properties(prepared));text=dayz_cfg.read_text();self.assertEqual(1,text.count('steamQueryPort ='));self.assertIn('steamQueryPort = 24003;',text)

   minecraft=root/'minecraft';minecraft.mkdir();spec={'configuration_root':str(minecraft),'arguments':[],'catalog_server_settings':declaration('minecraft.java.vanilla')}
   prepared=prepare_spec(spec,{'server_name':'Hello','max_players':10,'online_mode':False,'difficulty':'hard'});materialize_server_settings(prepared)
   text=(minecraft/'server.properties').read_text();self.assertIn('motd=Hello',text);self.assertIn('max-players=10',text);self.assertIn('online-mode=false',text);self.assertIn('difficulty=hard',text)

   pal=root/'pal';pal.mkdir();(pal/'PalWorldSettings.ini').write_text('[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(ServerName="Old",RCONPort=25575,ServerPlayerMaxNum=32)\n',encoding='utf-8')
   spec={'configuration_root':str(pal),'arguments':[],'catalog_server_settings':declaration('palworld.stable')}
   prepared=prepare_spec(spec,{'server_name':'New World','max_players':12});materialize_server_settings(prepared)
   text=(pal/'PalWorldSettings.ini').read_text();self.assertIn('ServerName="New World"',text);self.assertIn('ServerPlayerMaxNum=12',text);self.assertIn('RCONPort=25575',text)

   reforger=root/'reforger';reforger.mkdir();spec={'configuration_root':str(reforger),'arguments':[],'catalog_server_settings':declaration('armareforger.stable')}
   prepared=prepare_spec(spec,{'server_name':'Reforger','max_players':18,'visible':False});materialize_server_settings(prepared)
   payload=json.loads((reforger/'server.json').read_text());self.assertEqual('Reforger',payload['game']['name']);self.assertEqual(18,payload['game']['maxPlayers']);self.assertFalse(payload['game']['visible'])

   sat=root/'sat';sat.mkdir();spec={'configuration_root':str(sat),'arguments':[],'catalog_server_settings':declaration('satisfactory.stable')}
   prepared=prepare_spec(spec,{'max_players':8,'rotating_autosaves':5});materialize_server_settings(prepared)
   text=(sat/'Game.ini').read_text();self.assertIn('[/Script/Engine.GameSession]',text);self.assertIn('MaxPlayers=8',text);self.assertIn('mNumRotatingAutosaves=5',text)

 def test_argument_launch_and_command_bindings_are_allowlisted(self):
  valheim={'configuration_root':'/tmp/unused','arguments':['-name','Base','-public','1'],'catalog_server_settings':declaration('valheim.stable')}
  prepared=prepare_spec(valheim,{'server_name':'Valheim Test','public':False})
  self.assertEqual(['-name','Valheim Test','-public','0'],prepared['arguments'])
  self.assertEqual(['-name','Base','-public','1'],prepared['server_settings_base_arguments'])

  ark={'configuration_root':'/tmp/unused','arguments':['TheIsland_WP?Port=7777?QueryPort=27015'],'catalog_server_settings':declaration('arksurvivalascended.stable')}
  prepared=prepare_spec(ark,{'server_name':'ARK Test','max_players':20})
  self.assertIn('SessionName=ARK Test',prepared['arguments'][0]);self.assertIn('MaxPlayers=20',prepared['arguments'][0]);self.assertIn('Port=7777',prepared['arguments'][0])

  mindustry={'configuration_root':'/tmp/unused','arguments':['-jar','server.jar','config port 6567,host'],'catalog_server_settings':declaration('mindustry.github')}
  prepared=prepare_spec(mindustry,{'server_name':'Mindustry Test','max_players':30})
  command=prepared['arguments'][2];self.assertIn('config name "Mindustry Test"',command);self.assertIn('playerlimit 30',command);self.assertTrue(command.endswith('host'))

 def test_arma3_activation_argument_is_derived_from_private_config_root(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);spec={'configuration_root':str(root),'arguments':['-port=2302'],'catalog_server_settings':declaration('arma3.stable')}
   prepared=prepare_spec(spec,{'server_name':'A3','max_players':16});materialize_server_settings(prepared)
   self.assertIn(f'-config={root / "server.cfg"}',prepared['arguments'])
   text=(root/'server.cfg').read_text();self.assertIn('hostname = "A3";',text);self.assertIn('maxPlayers = 16;',text)

 def test_windows_materializer_matches_linux_contract(self):
  module_path=ROOT/'agents/windows/runtime/server_settings_runtime.py'
  spec=importlib.util.spec_from_file_location('windows_server_settings_runtime_tested',module_path);module=importlib.util.module_from_spec(spec);assert spec and spec.loader;spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);cfg=root/'serverDZ.cfg';cfg.write_text('hostname = "Old"; // comment\nhostname = "Duplicate";\nmaxPlayers = 60; // comment\nmaxPlayers = 32;\n',encoding='utf-8');base={'configuration_root':str(root),'arguments':[],'catalog_server_settings':declaration('dayz.stable')}
   prepared=module.prepare_spec(base,{'server_name':'Windows DayZ','max_players':14});self.assertEqual(['serverDZ.cfg'],module.materialize_server_settings(prepared))
   text=cfg.read_text();self.assertIn('hostname = "Windows DayZ";',text);self.assertIn('maxPlayers = 14;',text);self.assertEqual(1,text.count('hostname ='));self.assertEqual(1,text.count('maxPlayers ='))

 def test_dayz_profile_migration_preserves_server_settings_values(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);install=root/'dayz';install.mkdir();state=root/'instances/dayz-1';config={'agent_id':'agent-1','instance_storage_root':str(root/'instances')}
   dayz_runtime=runtime('dayz.stable');policy=default_policy(dayz_runtime)
   context={'install_path':str(install),'content_root':str(install),'instance_state_root':str(state),'ports':{'game':{'port':24000,'protocol':'udp'},'game_aux':{'port':24002,'protocol':'udp'},'steam_query':{'port':24003,'protocol':'udp'}},'catalog_runtime_policy':policy}
   instance={'instance_id':'dayz-1','agent_id':'agent-1','game_id':'dayz','environment_id':'dayz.stable','runtime_id':'dayz.stable','desired_state':'stopped'}
   with patch.object(instance_runtime,'STATE_DIR',root/'agent-state'):
    current=game_runtime.build_runtime_spec(config,instance,context);self.assertEqual(9,current['profile_version'])
    old=dict(current);old['profile_version']=8;old['server_settings_values']={'server_name':'Migrated DayZ','max_players':32}
    migrated,changed=game_runtime.migrate_runtime_spec(config,old)
   self.assertTrue(changed);self.assertEqual(9,migrated['profile_version']);self.assertEqual({'server_name':'Migrated DayZ','max_players':32},migrated['server_settings_values']);self.assertEqual({'server_name','max_players'},set(migrated['catalog_server_settings']['fields']))
   cfg=Path(migrated['configuration_root'])/'serverDZ.cfg';cfg.parent.mkdir(parents=True,exist_ok=True);cfg.write_text('hostname = "Old"; // comment\nhostname = "Duplicate";\nmaxPlayers = 60; // comment\nmaxPlayers = 20;\n',encoding='utf-8');materialize_server_settings(migrated);text=cfg.read_text();self.assertEqual(1,text.count('hostname ='));self.assertEqual(1,text.count('maxPlayers ='));self.assertIn('hostname = "Migrated DayZ";',text);self.assertIn('maxPlayers = 32;',text)

 def test_dayz_profile_migration_preserves_settings_when_profile_context_predates_settings(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);install=root/'dayz';install.mkdir();state=root/'instances/dayz-1';config={'agent_id':'agent-1','instance_storage_root':str(root/'instances')}
   dayz_runtime=runtime('dayz.stable');policy=default_policy(dayz_runtime)
   context={'install_path':str(install),'content_root':str(install),'instance_state_root':str(state),'ports':{'game':{'port':24000,'protocol':'udp'},'game_aux':{'port':24002,'protocol':'udp'},'steam_query':{'port':24003,'protocol':'udp'}},'catalog_runtime_policy':policy}
   instance={'instance_id':'dayz-1','agent_id':'agent-1','game_id':'dayz','environment_id':'dayz.stable','runtime_id':'dayz.stable','desired_state':'stopped'}
   with patch.object(instance_runtime,'STATE_DIR',root/'agent-state'):
    current=game_runtime.build_runtime_spec(config,instance,context)
    old=dict(current);old['profile_version']=8;old['server_settings_values']={'server_name':'Migrated DayZ','max_players':32}
    old['catalog_server_settings']=declaration('dayz.stable')
    legacy_context=dict(old.get('profile_context') or {});legacy_policy=dict(legacy_context.get('catalog_runtime_policy') or {});legacy_policy.pop('server_settings',None);legacy_context['catalog_runtime_policy']=legacy_policy;old['profile_context']=legacy_context
    migrated,changed=game_runtime.migrate_runtime_spec(config,old)
   self.assertTrue(changed);self.assertEqual(9,migrated['profile_version']);self.assertEqual(declaration('dayz.stable'),migrated['catalog_server_settings']);self.assertEqual({'server_name':'Migrated DayZ','max_players':32},migrated['server_settings_values'])

 def test_observed_dayz_surface_reads_real_parameters_and_protects_platform_fields(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);cfg=root/'serverDZ.cfg'
   cfg.write_text('hostname = "First"; // Server name\npassword = "join-secret";\npasswordAdmin = "admin-secret";\ndescription = "A server";\nenableWhitelist = 0;\nmaxPlayers = 60;\nverifySignatures = 2;\ndisable3rdPerson = 0;\nserverTimeAcceleration = 12;\nsteamQueryPort = 27016;\nhostname = "Effective";\nmaxPlayers = 32;\n',encoding='utf-8')
   spec={'configuration_root':str(root),'arguments':[],'environment_id':'dayz.stable','catalog_server_settings':declaration('dayz.stable'),'catalog_network_properties':[{'path':'serverDZ.cfg','key':'steamQueryPort','syntax':'semicolon'}]}
   surface=observed_surface(spec);fields=surface['fields'];by_key={item['key']:item for item in fields}
   self.assertEqual('Effective',by_key['hostname']['value']);self.assertEqual(32,by_key['maxPlayers']['value'])
   self.assertEqual(1,sum(item.get('logical_id')=='server_name' for item in fields));self.assertEqual(1,sum(item.get('logical_id')=='max_players' for item in fields))
   self.assertTrue(by_key['password']['secret']);self.assertIsNone(by_key['password']['value']);self.assertFalse(by_key['password']['editable']);self.assertTrue(by_key['password']['has_value'])
   self.assertTrue(by_key['passwordAdmin']['secret']);self.assertFalse(by_key['passwordAdmin']['editable'])
   self.assertFalse(by_key['steamQueryPort']['editable']);self.assertTrue(by_key['steamQueryPort']['managed'])
   self.assertEqual(2,by_key['verifySignatures']['value']);self.assertTrue(by_key['verifySignatures']['editable'])
   dynamic=normalize_dynamic_values(spec,{by_key['verifySignatures']['id']:1,by_key['disable3rdPerson']['id']:1})
   updated=dict(spec);updated['server_settings_dynamic_values']=dynamic
   self.assertEqual(['serverDZ.cfg'],materialize_dynamic_values(updated));text=cfg.read_text()
   self.assertIn('verifySignatures = 1;',text);self.assertIn('disable3rdPerson = 1;',text)
   with self.assertRaises(PermissionError):normalize_dynamic_values(spec,{by_key['steamQueryPort']['id']:24003})
   with self.assertRaises(PermissionError):normalize_dynamic_values(spec,{'cfg-forged':1})

 def test_dayz_extended_semantics_arrays_dependencies_and_comment_preservation(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);cfg=root/'serverDZ.cfg'
   cfg.write_text('respawnTime = 5; // respawn delay\nmotd[] = { "line1","line2" }; // message of the day\nmotdInterval = 1; // seconds\nlogMemory = 1; // requires doLogs\nadminLogPlacement = 0; // admin log\nspeedhackDetection = 1; // 1-10 float\nnetworkObjectBatchBandwidthLimit = 0.8; // bandwidth\npingWarning = 200; // yellow\npingCritical = 250; // red\nMaxPing = 300; // kick\nserverFpsWarning = 15; // fps\nclientPort = 2304; // capivara\nsteamQueryPort = 2305; // capivara\n',encoding='utf-8')
   spec={'configuration_root':str(root),'arguments':['-config=serverDZ.cfg'],'environment_id':'dayz.stable','catalog_server_settings':declaration('dayz.stable'),'catalog_network_properties':[{'path':'serverDZ.cfg','key':'clientPort','value':'24002','syntax':'semicolon'},{'path':'serverDZ.cfg','key':'steamQueryPort','value':'24003','syntax':'semicolon'}],'catalog_variables':{}}
   fields={f['key']:f for f in observed_surface(spec)['fields']}
   self.assertEqual(['line1','line2'],fields['motd[]']['value']);self.assertEqual('string_list',fields['motd[]']['type'])
   self.assertEqual('number',fields['speedhackDetection']['type']);self.assertEqual(1,fields['speedhackDetection']['min']);self.assertEqual(10,fields['speedhackDetection']['max'])
   self.assertEqual('number',fields['networkObjectBatchBandwidthLimit']['type']);self.assertFalse(fields['clientPort']['editable']);self.assertFalse(fields['steamQueryPort']['editable'])
   self.assertEqual('-doLogs',fields['logMemory']['requires_argument']);self.assertEqual('-adminLog',fields['adminLogPlacement']['requires_argument'])
   patch={fields['motd[]']['id']:['Welcome','No griefing'],fields['logMemory']['id']:2,fields['adminLogPlacement']['id']:True,fields['speedhackDetection']['id']:1.5,fields['networkObjectBatchBandwidthLimit']['id']:0.75,fields['pingWarning']['id']:180,fields['pingCritical']['id']:240,fields['MaxPing']['id']:300}
   dynamic=normalize_dynamic_values(spec,patch);updated=dict(spec);updated['server_settings_dynamic_values']=dynamic;updated=apply_runtime_dependencies(updated)
   self.assertIn('-doLogs',updated['arguments']);self.assertIn('-adminLog',updated['arguments']);materialize_dynamic_values(updated)
   text=cfg.read_text();self.assertIn('motd[] = { "Welcome", "No griefing" }; // message of the day',text);self.assertIn('logMemory = 2; // requires doLogs',text);self.assertIn('adminLogPlacement = 1; // admin log',text);self.assertIn('speedhackDetection = 1.5; // 1-10 float',text);self.assertIn('networkObjectBatchBandwidthLimit = 0.75; // bandwidth',text)
   materialize_network_properties(updated);text=cfg.read_text();self.assertIn('clientPort = 24002; // capivara',text);self.assertIn('steamQueryPort = 24003; // capivara',text)
   with self.assertRaises(ValueError):normalize_dynamic_values(spec,{fields['pingWarning']['id']:260,fields['pingCritical']['id']:250,fields['MaxPing']['id']:300})
   log_file_line='logFile = "server_console.log"; // log path\n';cfg.write_text(cfg.read_text()+log_file_line,encoding='utf-8');fields={f['key']:f for f in observed_surface(spec)['fields']}
   with self.assertRaises(ValueError):normalize_dynamic_values(spec,{fields['logFile']['id']:'../escape.log'})
   disabled=dict(updated);disabled['server_settings_dynamic_values']={fields['logMemory']['id']:0,fields['adminLogPlacement']['id']:False};disabled['server_settings_dependency_arguments']=['-doLogs','-adminLog'];disabled=apply_runtime_dependencies(disabled);self.assertNotIn('-doLogs',disabled['arguments']);self.assertNotIn('-adminLog',disabled['arguments'])

 def test_observed_json_ini_xml_and_unreal_surfaces_round_trip_extra_fields(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   factorio=root/'factorio';factorio.mkdir();(factorio/'server-settings.json').write_text(json.dumps({'name':'Factory','max_players':10,'visibility':{'public':True},'autosave_interval':7}),encoding='utf-8')
   spec={'configuration_root':str(factorio),'arguments':[],'environment_id':'factorio.stable','catalog_server_settings':declaration('factorio.stable')};surface=observed_surface(spec);extra=next(f for f in surface['fields'] if f['key']=='autosave_interval');updated=dict(spec);updated['server_settings_dynamic_values']=normalize_dynamic_values(spec,{extra['id']:11});materialize_dynamic_values(updated);self.assertEqual(11,json.loads((factorio/'server-settings.json').read_text())['autosave_interval'])

   sat=root/'sat';sat.mkdir();(sat/'Game.ini').write_text('[/Script/Engine.GameSession]\nMaxPlayers=8\nExtraSetting=42\n[/Script/FactoryGame.FGSaveSession]\nmNumRotatingAutosaves=3\n',encoding='utf-8')
   spec={'configuration_root':str(sat),'arguments':[],'environment_id':'satisfactory.stable','catalog_server_settings':declaration('satisfactory.stable')};surface=observed_surface(spec);extra=next(f for f in surface['fields'] if f['key']=='ExtraSetting');updated=dict(spec);updated['server_settings_dynamic_values']=normalize_dynamic_values(spec,{extra['id']:55});materialize_dynamic_values(updated);self.assertIn('ExtraSetting=55',(sat/'Game.ini').read_text())

   seven=root/'seven';seven.mkdir();(seven/'serverconfig.xml').write_text('<ServerSettings><property name="ServerName" value="Seven"/><property name="ServerMaxPlayerCount" value="8"/><property name="DayNightLength" value="60"/></ServerSettings>',encoding='utf-8')
   spec={'configuration_root':str(seven),'arguments':[],'environment_id':'sevendaystodie.stable','catalog_server_settings':declaration('sevendaystodie.stable')};surface=observed_surface(spec);extra=next(f for f in surface['fields'] if f['key']=='DayNightLength');updated=dict(spec);updated['server_settings_dynamic_values']=normalize_dynamic_values(spec,{extra['id']:90});materialize_dynamic_values(updated);self.assertIn('name="DayNightLength" value="90"',(seven/'serverconfig.xml').read_text())

   pal=root/'pal';pal.mkdir();(pal/'PalWorldSettings.ini').write_text('[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(ServerName="Pal",ServerPlayerMaxNum=12,RCONEnabled=True,DayTimeSpeedRate=1.000000)\n',encoding='utf-8')
   spec={'configuration_root':str(pal),'arguments':[],'environment_id':'palworld.stable','catalog_server_settings':declaration('palworld.stable')};surface=observed_surface(spec);extra=next(f for f in surface['fields'] if f['key']=='DayTimeSpeedRate');updated=dict(spec);updated['server_settings_dynamic_values']=normalize_dynamic_values(spec,{extra['id']:2.5});materialize_dynamic_values(updated);self.assertIn('DayTimeSpeedRate=2.5',(pal/'PalWorldSettings.ini').read_text())

 def test_observed_launcher_surface_uses_declared_types(self):
  valheim={'configuration_root':'/tmp','arguments':['-name','Viking','-public','1'],'environment_id':'valheim.stable','catalog_server_settings':declaration('valheim.stable')}
  fields={item['logical_id']:item for item in observed_surface(valheim)['fields']}
  self.assertEqual('Viking',fields['server_name']['value']);self.assertIs(True,fields['public']['value']);self.assertEqual('boolean',fields['public']['type'])
  ark={'configuration_root':'/tmp','arguments':['TheIsland_WP?Port=7777?QueryPort=27015?SessionName=ARK?MaxPlayers=24'],'environment_id':'arksurvivalascended.stable','catalog_server_settings':declaration('arksurvivalascended.stable')}
  fields={item['logical_id']:item for item in observed_surface(ark)['fields']};self.assertEqual('ARK',fields['server_name']['value']);self.assertEqual(24,fields['max_players']['value'])

 def test_windows_observed_surface_matches_linux_security_contract(self):
  module_path=ROOT/'agents/windows/runtime/server_settings_surface.py';specmod=importlib.util.spec_from_file_location('windows_server_settings_surface_tested',module_path);module=importlib.util.module_from_spec(specmod);assert specmod and specmod.loader;specmod.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'serverDZ.cfg').write_text('hostname="Win";\npassword="secret";\nmaxPlayers=20;\nsteamQueryPort=2305;\nverifySignatures=2;\n',encoding='utf-8')
   spec={'configuration_root':str(root),'arguments':[],'environment_id':'dayz.stable','catalog_server_settings':declaration('dayz.stable'),'catalog_network_properties':[{'path':'serverDZ.cfg','key':'steamQueryPort','syntax':'semicolon'}]};surface=module.observed_surface(spec);by_key={f['key']:f for f in surface['fields']}
   self.assertFalse(by_key['password']['editable']);self.assertIsNone(by_key['password']['value']);self.assertFalse(by_key['steamQueryPort']['editable'])
   updated=dict(spec);updated['server_settings_dynamic_values']=module.normalize_dynamic_values(spec,{by_key['verifySignatures']['id']:1});module.materialize_dynamic_values(updated);self.assertRegex((root/'serverDZ.cfg').read_text(),r'verifySignatures\s*=\s*1;')

 def test_observed_surface_masks_credentials_and_runtime_owned_network_values(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);ref=root/'reforger';ref.mkdir();(ref/'server.json').write_text(json.dumps({'bindPort':2001,'publicPort':2001,'game':{'name':'Ref','maxPlayers':16,'visible':True,'gameProperties':{'disableThirdPerson':False}},'extraGameplay':3}),encoding='utf-8')
   spec={'configuration_root':str(ref),'arguments':[],'environment_id':'armareforger.stable','catalog_server_settings':declaration('armareforger.stable')};fields={f['key']:f for f in observed_surface(spec)['fields']};self.assertFalse(fields['bindPort']['editable']);self.assertFalse(fields['publicPort']['editable']);self.assertTrue(fields['extraGameplay']['editable'])
   five=root/'five';five.mkdir();(five/'server.cfg').write_text('sv_hostname "Five"\nsv_licenseKey super-secret\nendpoint_add_udp "0.0.0.0:30120"\n',encoding='utf-8')
   spec={'configuration_root':str(five),'arguments':[],'environment_id':'fivem.stable','catalog_server_settings':declaration('fivem.stable'),'catalog_network_properties':[{'path':'server.cfg','key':'endpoint_add_udp','syntax':'command'}]};fields={f['key']:f for f in observed_surface(spec)['fields']};self.assertTrue(fields['sv_licenseKey']['secret']);self.assertIsNone(fields['sv_licenseKey']['value']);self.assertFalse(fields['sv_licenseKey']['editable']);self.assertFalse(fields['endpoint_add_udp']['editable'])

 def test_workspace_surface_maps_observed_ids_to_known_and_dynamic_desired_state(self):
  dayz=declaration('dayz.stable');captured={};surface={'fields':[{'id':'known-name','logical_id':'server_name','type':'string','editable':True,'secret':False},{'id':'known-players','logical_id':'max_players','type':'integer','editable':True,'secret':False,'min':1,'max':200},{'id':'extra-signatures','logical_id':None,'type':'integer','editable':True,'secret':False},{'id':'managed-port','logical_id':None,'type':'integer','editable':False,'managed':True,'secret':False}]}
  class ConfigRepo:
   def __init__(self,backend):pass
   def initialize(self):pass
   def get(self,**kwargs):return {'value':{'runtime_id':'dayz.stable','settings':{},'dynamic_values':{},'declaration':dayz},'revision':1,'checksum':'old'}
   def put(self,raw,updated_by=None):captured['value']=raw['value'];return {'configuration':{'revision':2,'checksum':'new'},'changed':True}
  service=workspace_service.CustomerInstanceWorkspaceService.__new__(workspace_service.CustomerInstanceWorkspaceService);service.root=ROOT;service.backend=object();service.require=lambda user,iid,perm:{'game_id':'dayz','runtime_id':'dayz.stable'};service.repo=type('Repo',(),{'workspace_policy':lambda self,iid:{}})();service._resolved_resource_policy=lambda context,policy:{'player_limit':32};service.files=type('Files',(),{'snapshot':lambda self,cid:{'command_id':cid,'instance_id':'instance-1','action':'settings_surface','status':'completed','result':surface}})()
  with patch.object(workspace_service,'runtime_workspace_capabilities',return_value={'server_settings':dayz}),patch.object(workspace_service,'ConfigurationRepository',ConfigRepo):
   result=service.save_server_settings({'username':'owner'},'instance-1',{'known-name':'Observed DayZ','known-players':24,'extra-signatures':1},'surface-1')
  self.assertEqual({'server_name':'Observed DayZ','max_players':24},captured['value']['settings']);self.assertEqual({'extra-signatures':1},captured['value']['dynamic_values']);self.assertEqual(32,captured['value']['player_limit']);self.assertTrue(result['changed'])
  with patch.object(workspace_service,'runtime_workspace_capabilities',return_value={'server_settings':dayz}),patch.object(workspace_service,'ConfigurationRepository',ConfigRepo):
   with self.assertRaises(ValueError):service.save_server_settings({'username':'owner'},'instance-1',{'known-players':33},'surface-1')
   with self.assertRaises(PermissionError):service.save_server_settings({'username':'owner'},'instance-1',{'managed-port':24003},'surface-1')

 def test_settings_surface_is_internal_and_does_not_require_file_manager_permission(self):
  service=workspace_service.CustomerInstanceWorkspaceService.__new__(workspace_service.CustomerInstanceWorkspaceService);service.root=ROOT;service.require=lambda user,iid,perm:{'agent_id':'agent-1','game_id':'dayz','runtime_id':'dayz.stable'}
  calls={}
  class Files:
   def enqueue(self,**kwargs):calls.update(kwargs);return {'command_id':'surface-1','status':'queued'}
  service.files=Files();result=service.queue_server_settings_surface({'username':'owner'},'instance-1');self.assertEqual('surface-1',result['command_id']);self.assertEqual('settings_surface',calls['action']);self.assertIsNone(calls.get('path'));self.assertIn('server_name',calls['payload']['declaration']['fields'])
  with self.assertRaises(ValueError):service.queue_file({'username':'owner'},'instance-1','settings_surface')

 def test_workspace_persists_canonical_declaration_and_merges_partial_values(self):
  dayz=declaration('dayz.stable');captured={}
  class ConfigRepo:
   def __init__(self,backend):pass
   def initialize(self):pass
   def get(self,**kwargs):return {'value':{'runtime_id':'dayz.stable','settings':{'server_name':'Existing'},'declaration':dayz},'revision':1,'checksum':'old'}
   def put(self,raw,updated_by=None):
    captured['raw']=raw;captured['updated_by']=updated_by
    return {'configuration':{'value':raw['value'],'revision':2,'checksum':'new'},'changed':True}
  service=workspace_service.CustomerInstanceWorkspaceService.__new__(workspace_service.CustomerInstanceWorkspaceService);service.root=ROOT;service.backend=object()
  service.require=lambda user,instance_id,permission:{'game_id':'dayz','runtime_id':'dayz.stable'}
  service.repo=type('Repo',(),{'workspace_policy':lambda self,instance_id:{}})()
  service._resolved_resource_policy=lambda context,policy:{'player_limit':10}
  with patch.object(workspace_service,'runtime_workspace_capabilities',return_value={'server_settings':dayz}),patch.object(workspace_service,'ConfigurationRepository',ConfigRepo):
   result=service.save_server_settings({'username':'owner'},'instance-1',{'max_players':8})
  value=captured['raw']['value'];self.assertEqual('dayz.stable',value['runtime_id']);self.assertEqual({'server_name':'Existing','max_players':8},value['settings']);self.assertEqual(dayz,value['declaration']);self.assertEqual(value['settings'],result['values'])


 def test_satisfactory_and_luanti_existing_specs_migrate_to_configured_profiles(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);instance_runtime.STATE_DIR=root/'agent-state';config={'agent_id':'agent-1','instance_storage_root':str(root/'instances')}
   sat=root/'sat';sat.mkdir();(sat/'FactoryServer.sh').write_text('',encoding='utf-8');sat_state=root/'instances/sat-1'
   sat_context={'install_path':str(sat),'content_root':str(sat),'instance_state_root':str(sat_state),'ports':{'game_udp':{'port':7777,'protocol':'udp'},'game_tcp':{'port':7777,'protocol':'tcp'},'reliable_tcp':{'port':7778,'protocol':'tcp'}},'catalog_runtime_policy':{'runtime_id':'satisfactory.stable','executable':'FactoryServer.sh','working_directory':'.','arguments':[],'environment':{},'server_settings':declaration('satisfactory.stable')}}
   sat_spec=game_runtime.build_runtime_spec(config,{'instance_id':'sat-1','agent_id':'agent-1','game_id':'satisfactory','environment_id':'satisfactory.stable'},sat_context);old=dict(sat_spec);old['profile_version']=1;old['bind_paths']=[];old['seed_directories']=[]
   migrated,changed=game_runtime.migrate_runtime_spec(config,old);self.assertTrue(changed);self.assertEqual(2,migrated['profile_version']);self.assertEqual(str(sat_state/'config'),migrated['configuration_root']);self.assertTrue(migrated['bind_paths'])
   lua=root/'luanti';(lua/'luanti-5.17.0/bin').mkdir(parents=True);(lua/'luanti-5.17.0/bin/luantiserver').write_text('',encoding='utf-8');lua_state=root/'instances/lua-1'
   lua_context={'install_path':str(lua),'content_root':str(lua),'instance_state_root':str(lua_state),'ports':{'game':{'port':30000,'protocol':'udp'}},'catalog_runtime_policy':{'runtime_id':'luanti.stable','executable':'luanti-5.17.0/bin/luantiserver','working_directory':'.','arguments':[],'environment':{},'server_settings':declaration('luanti.stable')}}
   lua_spec=game_runtime.build_runtime_spec(config,{'instance_id':'lua-1','agent_id':'agent-1','game_id':'luanti','environment_id':'luanti.stable'},lua_context);old=dict(lua_spec);old['profile_version']=1;old['arguments']=[x for x in lua_spec['arguments'] if x not in {'--config',str(lua_state/'config/minetest.conf')}]
   migrated,changed=game_runtime.migrate_runtime_spec(config,old);self.assertTrue(changed);self.assertEqual(2,migrated['profile_version']);self.assertIn('--config',migrated['arguments']);self.assertIn(str(lua_state/'config/minetest.conf'),migrated['arguments'])


 def test_dashboard_and_database_policy_contracts_match(self):
  module_path=ROOT/'dashboard/customer_instance_policy.py'
  spec=importlib.util.spec_from_file_location('dashboard_customer_instance_policy_tested',module_path);module=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[spec.name]=module;spec.loader.exec_module(module)
  self.assertEqual(INSTANCE_PERMISSIONS,module.INSTANCE_PERMISSIONS)
  for name in ('viewer','operator','manager'):
   self.assertEqual(set(PERMISSION_PRESETS[name]),set(module.PERMISSION_PRESETS[name]))
  dayz=declaration('dayz.stable')
  self.assertEqual({'max_players':4},module.validate_server_settings({'max_players':4},dayz,player_limit=4))
  with self.assertRaises(ValueError):module.validate_server_settings({'max_players':5},dayz,player_limit=4)


if __name__=='__main__':unittest.main()
