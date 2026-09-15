#!/usr/bin/env python3
from __future__ import annotations
import json,os,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/'dashboard',ROOT/'database',ROOT/'core'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from customer_instance_policy import effective_content_policy,enforce_content_upload,enforce_managed_content_mutation
from customer_instance_workspace_service import CustomerInstanceWorkspaceService

class _Repo:
 def workspace_policy(self,instance_id):return {}
class _Files:
 def __init__(self):self.calls=[]
 def enqueue(self,**kwargs):self.calls.append(kwargs);return kwargs

class UniversalContentCleanupTest(unittest.TestCase):
 def rules(self):return {'mod_paths':['mods'],'plugin_paths':['plugins'],'workshop_paths':['workshop'],'runtime_extensions':['.jar'],'protected_paths':['runtime','.dsm']}
 def policy(self):return effective_content_policy({'mods':True,'plugins':True,'workshop':True,'external_upload':True},{'mods':True,'plugins':True,'workshop':True,'external_upload':True})
 def test_entitlement_never_grants_direct_native_content_write(self):
  for path in ('mods/example.jar','plugins/example.jar','workshop/221100/item.bin'):
   with self.subTest(path=path),self.assertRaisesRegex(PermissionError,'UCP-owned'):enforce_content_upload(path,policy=self.policy(),runtime_rules=self.rules())
  enforce_content_upload('config/server.properties',policy=self.policy(),runtime_rules=self.rules())
 def test_controller_rejects_all_managed_file_mutations_before_queue(self):
  service=CustomerInstanceWorkspaceService.__new__(CustomerInstanceWorkspaceService);service.repo=_Repo();service.files=_Files()
  service.require=lambda user,instance_id,permission:{'agent_id':'agent','game_id':'minecraft','runtime_id':'minecraft.java.neoforge','contract_metadata':{}}
  service._resolved_resource_policy=lambda context,policy:{}
  service._file_command_policy=lambda context,policy:{'content_policy':self.policy().as_dict(),'file_policy':self.rules()}
  cases=[('write_text',{'path':'mods/a.jar'}),('upload',{'path':'plugins/a.jar'}),('mkdir',{'path':'mods/new'}),('delete',{'path':'mods/a.jar'}),('move',{'path':'mods/a.jar','target_path':'config/a.jar'}),('move',{'path':'config/a.jar','target_path':'plugins/a.jar'}),('extract',{'path':'upload.zip','target_path':'mods'})]
  for action,kwargs in cases:
   with self.subTest(action=action,kwargs=kwargs),self.assertRaisesRegex(PermissionError,'UCP-owned'):service.queue_file({'username':'customer'},'instance',action,**kwargs)
  self.assertEqual(service.files.calls,[])
  queued=service.queue_file({'username':'customer'},'instance','write_text',path='config/server.properties',payload={'content':'ok'})
  self.assertEqual(queued['path'],'config/server.properties');self.assertEqual(len(service.files.calls),1)
 def test_agent_guards_match_on_linux_and_windows(self):
  for platform in ('linux','windows'):
   runtime=ROOT/'agents'/platform/'runtime';source='''\nfrom pathlib import Path\nimport instance_files_client as m\npolicy={"content_policy":{"mods_allowed":True,"plugins_allowed":True,"workshop_allowed":True,"external_upload_allowed":True,"custom_runtime_allowed":False},"file_policy":{"mod_paths":["mods"],"plugin_paths":["plugins"],"workshop_paths":["workshop"],"runtime_extensions":[".jar"]}}\nmanaged=[Path("mods/a.jar"),Path("plugins/a.jar"),Path("workshop/a.bin")]\nfor rel in managed:\n try:\n  (m._guard_path_policy(rel,policy,mutation=True,upload=True) if hasattr(m,"_guard_path_policy") else m._guard(rel,policy,True,True))\n except PermissionError as exc:\n  assert "UCP-owned" in str(exc)\n else: raise AssertionError(rel)\nrel=Path("config/server.properties")\n(m._guard_path_policy(rel,policy,mutation=True,upload=True) if hasattr(m,"_guard_path_policy") else m._guard(rel,policy,True,True))\n'''
   env={**os.environ,'PYTHONPATH':str(runtime),'PROGRAMDATA':str(ROOT/'tmp-u11-programdata')}
   cp=subprocess.run([sys.executable,'-c',source],cwd=ROOT,env=env,capture_output=True,text=True)
   self.assertEqual(cp.returncode,0,f'{platform}: {cp.stderr}')
 def test_agent_mutating_calls_use_the_managed_path_guard(self):
  linux=(ROOT/'agents/linux/runtime/instance_files_client.py').read_text();windows=(ROOT/'agents/windows/runtime/instance_files_client.py').read_text()
  for marker in ('_guard_path_policy(rel, policy, mutation=True)','_guard_path_policy(source_rel, policy, mutation=True)','_guard_path_policy(target.relative_to(root), policy, mutation=True, upload=True)'):self.assertIn(marker,linux)
  for marker in ('_guard(rel,policy,True)','_guard(sr,policy,True)','_guard(target.relative_to(root),policy,True,True)'):self.assertIn(marker,windows)
 def test_legacy_content_mutation_entrypoints_fail_closed(self):
  env={**os.environ,'DSM_ROOT':str(ROOT),'DSM_OUTPUT_FORMAT':'json'}
  commands=[['bash','installer/content_manager.sh','install','request.json','/tmp/instance'],['bash','installer/catalog.sh','content','install','request.json','/tmp/instance','--json'],['bash','dashboard/api/catalog.sh','installed','/tmp/instance'],['bash','installer/update_monitor.sh','apply-content','request.json','/tmp/instance']]
  for command in commands:
   with self.subTest(command=command):
    cp=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True);self.assertEqual(cp.returncode,3,cp.stderr or cp.stdout)
    self.assertIn('retir', (cp.stdout+cp.stderr).lower())
 def test_only_current_frontends_remain_and_use_ucp(self):
  self.assertFalse((ROOT/'dashboard/web/customer-instance.js').exists());self.assertFalse((ROOT/'dashboard/web/catalog-v2.js').exists())
  current=(ROOT/'dashboard/web/customer-instance-v2.js').read_text();self.assertIn('/api/customer/instance/workspace',current);self.assertIn('/content',current)
  legacy_routes=('/api/catalog/install','/api/catalog/remove','/api/catalog/verify','/api/catalog/rollback','/api/catalog/installed')
  for path in (ROOT/'dashboard/web').glob('*.js'):
   text=path.read_text(encoding='utf-8')
   for route in legacy_routes:self.assertNotIn(route,text,f'{path.name}: {route}')
 def test_http_and_route_contracts_retire_legacy_mutation(self):
  server=(ROOT/'dashboard/server.py').read_text();routes=(ROOT/'dashboard/api/routes.conf').read_text();manager=(ROOT/'installer/content_manager.sh').read_text()
  self.assertIn('LEGACY_CATALOG_CONTENT_MUTATIONS',server);self.assertIn('legacy_content_path_retired',server);self.assertIn('LEGACY_INSTANCE_FILE_MUTATIONS',server);self.assertIn('legacy_file_mutation_retired',server)
  for route in ('/api/catalog/installed','/api/catalog/install','/api/catalog/remove','/api/catalog/verify','/api/catalog/rollback'):self.assertNotIn(route,routes)
  for route in ('/api/mods','/api/mods/update','/api/mods/install','/api/mods/remove'):self.assertNotIn(route,routes)
  self.assertFalse((ROOT/'dashboard/api/mods.sh').exists())
  cap=(ROOT/'bin/cap').read_text();self.assertNotIn('cap mods',cap);self.assertNotIn('mods/mods.sh',cap)
  self.assertNotIn('api_mods_real',server);self.assertNotIn('mods/state.sh',server)
  self.assertNotIn('provider_install',manager);self.assertNotIn('content_stage_current',manager);self.assertIn('legacy_content_path_retired',manager)
if __name__=='__main__':unittest.main()
