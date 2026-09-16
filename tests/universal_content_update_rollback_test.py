#!/usr/bin/env python3
from __future__ import annotations
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/'core',ROOT/'database',ROOT/'dashboard',ROOT/'agents/linux/runtime'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from backend import DatabaseConfig
from backend_factory import create_backend
from content_repository import ContentRepository
from agent_heartbeat_api import record_agent_heartbeat
import content_client

def _artifact(name,digest='a'):
 return {'provider':'modrinth','url':f'https://cdn.modrinth.com/{name}.jar','filename':f'{name}.jar','sha512':digest*128}
def _member(cid,name=None,digest='a'):
 name=name or cid;return {'content_id':cid,'path':f'mods/{name}.jar','required':True,'artifact':_artifact(name,digest)}
def _bundle(version,members):
 return {'provider':'modrinth','provider_project_id':'pack-project','provider_version_id':version,'minecraft_version':'1.21.1','loader_id':'fabric','loader_version':'0.16.0','manifest_kind':'mrpack-v1','members':members,'override_roots':['overrides']}

class UniversalContentUpdateRollbackTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver='sqlite',database=str(Path(self.tmp.name)/'db.sqlite')));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute('INSERT INTO nodes(id,name,role) VALUES (?,?,?)',('ctrl-node','Controller','controller'));c.execute('INSERT INTO nodes(id,name,role) VALUES (?,?,?)',('agent-node','Agent','agent'));c.execute('INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)',('ctrl','ctrl-node','Controller'));c.execute('INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)',('agent','ctrl','agent-node','Agent','active'));customer=c.execute('INSERT INTO customers(controller_id,name) VALUES (?,?)',('ctrl','Customer'));c.execute('INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)',('inst','agent-node','minecraft','MC','stopped','ctrl','agent',customer.lastrowid))
  self.repo=ContentRepository(self.backend);self.repo.initialize()
 def tearDown(self):self.backend.close();self.tmp.cleanup()
 def assignment(self,version,digest='a'):
  return {'instance_id':'inst','content_id':'mod-one','content_type':'mod','provider':'modrinth','version':version,'artifact':_artifact('mod-one',digest),'provenance':{'minecraft_provider':{'project_id':'project','version_id':version}}}
 def parent(self,version,digest='b'):
  return {'instance_id':'inst','content_id':'pack','content_type':'modpack','provider':'modrinth','version':version,'artifact':{'provider':'modrinth','url':f'https://cdn.modrinth.com/pack-{version}.mrpack','filename':'pack.mrpack','sha512':digest*128,'archive':True},'provenance':{'minecraft_modpack':{'project_id':'pack-project','version_id':version}}}
 def child(self,cid,version='1',digest='a'):
  return {'instance_id':'inst','content_id':cid,'content_type':'mod','provider':'modrinth','version':version,'artifact':_artifact(cid,digest)}
 def test_individual_rollback_creates_new_revision_from_history(self):
  first=self.repo.put(self.assignment('1','a'),requested_by='test')['assignment'];second=self.repo.put(self.assignment('2','b'),requested_by='test')['assignment'];result=self.repo.rollback('inst','mod-one',first['revision'],requested_by='alice',reason='customer');current=result['assignment']
  self.assertEqual(second['revision'],2);self.assertEqual(current['revision'],3);self.assertEqual(current['version'],'1');self.assertEqual(current['security_state'],'unscanned');self.assertEqual(current['provenance']['rollback']['restored_revision'],1);self.assertEqual([x['revision'] for x in self.repo.history(current['assignment_id'])],[3,2,1])
 def test_agent_readiness_rollback_converges_controller_desired_state(self):
  old=self.repo.put(self.assignment('1','a'))['assignment'];self.repo.record_agent_state('agent',[{'instance_id':'inst','content_id':'mod-one','desired_revision':old['revision'],'applied_revision':old['revision'],'desired_checksum':old['checksum'],'applied_checksum':old['checksum'],'status':'applied','installed_version':'1','security_state':'clean'}]);new=self.repo.put(self.assignment('2','b'))['assignment']
  accepted=self.repo.record_agent_state('agent',[{'instance_id':'inst','content_id':'mod-one','desired_revision':new['revision'],'applied_revision':old['revision'],'desired_checksum':new['checksum'],'applied_checksum':old['checksum'],'status':'rolled_back','readiness':'rolled_back','installed_version':'1','security_state':'clean','last_error':'readiness failed'}]);current=self.repo.get('inst','mod-one')
  self.assertEqual(accepted,1);self.assertEqual(current['version'],'1');self.assertEqual(current['revision'],3);self.assertEqual(current['provenance']['rollback']['reason'],'readiness failed');self.assertEqual(self.repo.desired_for_agent('agent')[0]['revision'],3)
 def test_heartbeat_returns_new_rollback_revision_after_agent_recovery(self):
  old=self.repo.put(self.assignment('1','a'))['assignment'];self.repo.record_agent_state('agent',[{'instance_id':'inst','content_id':'mod-one','desired_revision':old['revision'],'applied_revision':old['revision'],'desired_checksum':old['checksum'],'applied_checksum':old['checksum'],'status':'applied','installed_version':'1','security_state':'clean'}]);new=self.repo.put(self.assignment('2','b'))['assignment']
  response=record_agent_heartbeat('agent',{'agent_id':'agent','content_state':[{'instance_id':'inst','content_id':'mod-one','desired_revision':new['revision'],'applied_revision':old['revision'],'desired_checksum':new['checksum'],'applied_checksum':old['checksum'],'status':'rolled_back','readiness':'rolled_back','installed_version':'1','security_state':'clean','last_error':'readiness failed'}]},backend=self.backend,root=ROOT)
  self.assertEqual(response['content_count'],1);command=response['content_commands'][0];self.assertEqual(command['version'],'1');self.assertEqual(command['revision'],3);self.assertEqual(command['provenance']['rollback']['restored_revision'],1)
 def test_agent_reports_prior_applied_revision_when_activation_rolls_back(self):
  with tempfile.TemporaryDirectory() as td:
   state=Path(td)/'state.json';previous={'instance_id':'inst','content_id':'mod-one','desired_revision':1,'applied_revision':1,'desired_checksum':'a'*64,'applied_checksum':'a'*64,'status':'applied','installed_version':'1','managed_path':'/tmp/old','security_state':'clean','provider':'modrinth','content_type':'mod','package_id':'project:old','game_id':'minecraft','target':'mods/mod-one','security_policy_version':1};state.write_text(json.dumps(previous));cmd={'instance_id':'inst','content_id':'mod-one','revision':2,'checksum':'b'*64,'version':'2','provider':'local','target':'mods/mod-one','artifact':{}}
   with patch.object(content_client,'_state_path',return_value=state),patch.object(content_client,'_install',side_effect=content_client.ContentActivationError('readiness failed')):result=content_client._apply({'agent_id':'agent'},cmd)
  self.assertEqual(result['status'],'rolled_back');self.assertEqual(result['applied_revision'],1);self.assertEqual(result['applied_checksum'],'a'*64);self.assertEqual(result['installed_version'],'1');self.assertEqual(result['package_id'],'project:old');self.assertEqual(result['provider'],'modrinth')
 def test_bundle_child_readiness_failure_rolls_back_parent_bundle(self):
  v1=_bundle('v1',[_member('a'),_member('b')]);self.repo.put_bundle(self.parent('1'),v1,[self.child('a'),self.child('b')],requested_by='test');old_b=self.repo.get('inst','b')
  v2=_bundle('v2',[_member('b',digest='c'),_member('c')]);self.repo.put_bundle(self.parent('2','c'),v2,[self.child('b','2','c'),self.child('c')],requested_by='test');new_b=self.repo.get('inst','b')
  self.repo.record_agent_state('agent',[{'instance_id':'inst','content_id':'b','desired_revision':new_b['revision'],'applied_revision':old_b['revision'],'desired_checksum':new_b['checksum'],'applied_checksum':old_b['checksum'],'status':'rolled_back','readiness':'rolled_back','installed_version':'1','security_state':'clean','last_error':'bundle readiness failed'}])
  self.assertEqual(self.repo.get('inst','pack')['version'],'1');self.assertEqual(int(self.repo._bundle_row('inst','pack')['revision']),3);self.assertEqual(self.repo.get('inst','a')['desired_state'],'installed');self.assertEqual(self.repo.get('inst','c')['desired_state'],'absent')
 def test_rollback_revision_can_reuse_restored_target_but_rescans_it(self):
  with tempfile.TemporaryDirectory() as td:
   managed=Path(td)/'managed';managed.mkdir();(managed/'old.jar').write_bytes(b'old');previous={'status':'rolled_back','installed_version':'1','managed_path':str(managed),'provider':'modrinth','package_id':'project:old','target':'mods/mod-one','game_id':'minecraft'};command={'desired_state':'installed','version':'1','provider':'modrinth','target':'mods/mod-one','game_id':'minecraft','artifact':{'package_id':'project:old'}}
   with patch.object(content_client,'_managed_path_current',return_value=True):self.assertTrue(content_client._reuse_installed({'agent_id':'agent'},previous,command,content_client._source_metadata(command)))
 def test_activation_projection_rollback_is_reported_to_controller(self):
  previous={'instance_id':'inst','content_id':'mod-one','desired_revision':1,'applied_revision':1,'desired_checksum':'a'*64,'applied_checksum':'a'*64,'status':'applied','installed_version':'1','managed_path':'/tmp/old','security_state':'clean','security_policy_version':1,'provider':'modrinth','content_type':'mod','package_id':'project:old','game_id':'minecraft','target':'mods/mod-one'};command={'instance_id':'inst','content_id':'mod-one','revision':2,'checksum':'b'*64,'version':'2','provider':'modrinth','target':'mods/mod-one','artifact':{'package_id':'project:new'}};applied={**previous,'desired_revision':2,'applied_revision':2,'desired_checksum':'b'*64,'applied_checksum':'b'*64,'installed_version':'2','package_id':'project:new'}
  with tempfile.TemporaryDirectory() as td:
   state=Path(td)/'state.json';state.write_text(json.dumps(previous))
   with patch.object(content_client,'_dependency_state',return_value=previous),patch.object(content_client,'_apply',return_value=dict(applied)),patch.object(content_client,'_state_path',return_value=state),patch.object(content_client,'synchronize_activation_state',return_value=[{'instance_id':'inst'}]),patch.object(content_client,'apply_activation_snapshots',side_effect=content_client.ContentActivationApplyError('projection readiness failed')):
    result=content_client.apply_content_commands({'agent_id':'agent'},[command])[0]
   self.assertEqual(result['status'],'rolled_back');self.assertEqual(result['applied_revision'],1);self.assertEqual(result['package_id'],'project:old');self.assertEqual(json.loads(state.read_text())['status'],'rolled_back')
 def test_activation_projection_rollback_failure_is_not_reported_as_recovered(self):
  command={'instance_id':'inst','content_id':'mod-one','revision':2,'checksum':'b'*64};applied={'instance_id':'inst','content_id':'mod-one','desired_revision':2,'applied_revision':2,'desired_checksum':'b'*64,'applied_checksum':'b'*64,'status':'applied','installed_version':'2','security_state':'clean'}
  with tempfile.TemporaryDirectory() as td:
   state=Path(td)/'state.json'
   with patch.object(content_client,'_dependency_state',return_value={}),patch.object(content_client,'_apply',return_value=dict(applied)),patch.object(content_client,'_state_path',return_value=state),patch.object(content_client,'synchronize_activation_state',return_value=[{'instance_id':'inst'}]),patch.object(content_client,'apply_activation_snapshots',side_effect=content_client.ContentActivationRollbackError('rollback failed')):
    result=content_client.apply_content_commands({'agent_id':'agent'},[command])[0]
   self.assertEqual(result['status'],'rollback_failed');self.assertEqual(result['readiness'],'rollback_failed')
 def test_linux_windows_rollback_report_contract_stays_in_parity(self):
  linux=(ROOT/'agents/linux/runtime/content_client.py').read_text(encoding='utf-8');windows=(ROOT/'agents/windows/runtime/content_client.py').read_text(encoding='utf-8')
  for marker in ('status":"rolled_back','applied_revision":int(previous.get("applied_revision"))','readiness":"rolled_back','ContentRollbackError as exc'):
   self.assertIn(marker,linux);self.assertIn(marker,windows)
 def test_bundle_diff_and_rollback_restore_composed_revision(self):
  v1=_bundle('v1',[_member('a'),_member('b')]);self.repo.put_bundle(self.parent('1'),v1,[self.child('a'),self.child('b')],requested_by='test');v2=_bundle('v2',[_member('b',digest='c'),_member('c')]);diff=self.repo.bundle_diff('inst','pack',v2);self.assertEqual(diff,{'added':['c'],'removed':['a'],'updated':['b'],'unchanged':[]})
  self.repo.put_bundle(self.parent('2','c'),v2,[self.child('b','2','c'),self.child('c')],requested_by='test');rolled=self.repo.rollback_bundle('inst','pack',1,requested_by='alice',reason='customer');current=self.repo.get('inst','pack')
  self.assertEqual(rolled['bundle_revision'],3);self.assertEqual(current['version'],'1');self.assertEqual(self.repo.get('inst','a')['desired_state'],'installed');self.assertEqual(self.repo.get('inst','c')['desired_state'],'absent');self.assertEqual([int(x['revision']) for x in self.repo.bundle_history('inst','pack')],[3,2,1])

if __name__=='__main__':unittest.main()