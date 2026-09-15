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
   dayz=root/'dayz';dayz.mkdir();spec={'configuration_root':str(dayz),'arguments':[],'catalog_server_settings':declaration('dayz.stable')}
   prepared=prepare_spec(spec,{'server_name':'Capivara Test','max_players':24});self.assertEqual(['serverDZ.cfg'],materialize_server_settings(prepared))
   text=(dayz/'serverDZ.cfg').read_text();self.assertIn('hostname = "Capivara Test";',text);self.assertIn('maxPlayers = 24;',text)

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
   root=Path(td);base={'configuration_root':str(root),'arguments':[],'catalog_server_settings':declaration('dayz.stable')}
   prepared=module.prepare_spec(base,{'server_name':'Windows DayZ','max_players':14});self.assertEqual(['serverDZ.cfg'],module.materialize_server_settings(prepared))
   text=(root/'serverDZ.cfg').read_text();self.assertIn('hostname = "Windows DayZ";',text);self.assertIn('maxPlayers = 14;',text)

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
