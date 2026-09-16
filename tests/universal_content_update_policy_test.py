#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard',ROOT/'dashboard/workers',ROOT/'agents/linux/runtime'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from content_platform import normalize_assignment
from content_update_dispatch_repository import ContentUpdateDispatchRepository
from server_update_schema import content_update_ddl
from content_update_worker import ContentUpdateWorker
import content_client


class _FakeRepository:
 def __init__(self,items):self.items=list(items);self.claimed=[];self.completed=[];self.failed=[]
 def initialize(self):return None
 def due(self,limit=200):return list(self.items)[:limit]
 def claim(self,item):self.claimed.append(item['content_id']);return True
 def complete(self,item,revision):self.completed.append((item['content_id'],revision))
 def fail(self,item,error):self.failed.append((item['content_id'],str(error)))


class _FakeContent:
 def __init__(self,revisions,versions=None,artifacts=None):self.revisions=dict(revisions);self.versions=dict(versions or {});self.artifacts=dict(artifacts or {})
 def get(self,instance_id,content_id):return {'instance_id':instance_id,'content_id':content_id,'revision':self.revisions[content_id],'version':self.versions.get(content_id),'artifact':self.artifacts.get(content_id,{})}


class _FakeService:
 def __init__(self,revisions,fail=None,versions=None,artifacts=None):self.content=_FakeContent(revisions,versions,artifacts);self.calls=[];self.fail=set(fail or [])
 def mutate(self,user,instance_id,content_id,action,body):
  self.calls.append((user['role'],user['username'],instance_id,content_id,action,body))
  if content_id in self.fail:raise RuntimeError('resolver unavailable')
  return {'changed':True}


class UniversalContentUpdatePolicyTest(unittest.TestCase):
 def test_policy_dispatch_fails_closed_without_maintenance_window(self):
  repo=object.__new__(ContentUpdateDispatchRepository);now=datetime(2026,9,17,18,30,tzinfo=timezone.utc)
  allowed,mode=repo._eligible({'override_mode':'automatic','instance_mode':None},now);self.assertTrue(allowed);self.assertEqual(mode,'automatic')
  allowed,mode=repo._eligible({'override_mode':'manual','instance_mode':'automatic','instance_timezone':'UTC','instance_weekdays_json':'[3]','instance_start_time':'18:00','instance_duration_minutes':60,'instance_check_interval_seconds':900,'instance_backup_before_update':1},now);self.assertFalse(allowed);self.assertEqual(mode,'manual')
  allowed,reason=repo._eligible({'override_mode':'maintenance','instance_mode':None},now);self.assertFalse(allowed);self.assertEqual(reason,'maintenance_without_instance_policy')
  allowed,mode=repo._eligible({'override_mode':'maintenance','instance_mode':'manual','instance_timezone':'UTC','instance_weekdays_json':'[3]','instance_start_time':'18:00','instance_duration_minutes':60,'instance_check_interval_seconds':900,'instance_backup_before_update':1},now);self.assertTrue(allowed);self.assertEqual(mode,'maintenance')
 def test_workshop_time_updated_is_canonical_desired_version_and_breaks_reuse(self):
  base={'agent_id':'agent-1','instance_id':'instance-1','content_id':'steam-workshop:123','game_id':'dayz','content_type':'workshop','desired_state':'installed','provider':'steam-workshop','target':'workshop/steam-workshop:123','artifact':{'provider':'steam-workshop','package_id':'221100:123'},'metadata':{'steam_workshop':{'published_file_id':'123','consumer_app_id':'221100','time_updated':100}}}
  old=normalize_assignment(base);new=normalize_assignment({**base,'version':'latest','metadata':{'steam_workshop':{'published_file_id':'123','consumer_app_id':'221100','time_updated':101}}})
  self.assertEqual(old['version'],'100');self.assertEqual(new['version'],'101');self.assertNotEqual(old['checksum'],new['checksum'])
  previous={'status':'applied','installed_version':'100','provider':'steam-workshop','package_id':'221100:123','target':old['target'],'game_id':'dayz','managed_path':'/managed/workshop'}
  command={**new,'revision':2};source_meta=content_client._source_metadata(command)
  with patch('content_client._managed_path_current',return_value=True):self.assertFalse(content_client._reuse_installed({},previous,command,source_meta))
 def test_windows_and_linux_reuse_contract_both_compare_desired_version(self):
  linux=(ROOT/'agents/linux/runtime/content_client.py').read_text(encoding='utf-8');windows=(ROOT/'agents/windows/runtime/content_client.py').read_text(encoding='utf-8');needle='str(previous.get("installed_version"))!=str(cmd.get("version") or "latest")'
  self.assertIn(needle,linux);self.assertIn(needle,windows)
 def test_non_workshop_version_is_not_rewritten_by_metadata(self):
  item=normalize_assignment({'agent_id':'agent-1','instance_id':'instance-1','content_id':'mod-a','game_id':'minecraft','content_type':'mod','provider':'modrinth','version':'v2','artifact':{'provider':'modrinth','package_id':'p:v2'},'metadata':{'steam_workshop':{'time_updated':999}}})
  self.assertEqual(item['version'],'v2')
 def test_worker_routes_updates_through_canonical_u9_service(self):
  items=[{'agent_id':'a1','instance_id':'i1','content_id':'mod-a','available_version':'11','assignment_revision':4},{'agent_id':'a1','instance_id':'i1','content_id':'mod-b','available_version':'22','assignment_revision':7}]
  repository=_FakeRepository(items);service=_FakeService({'mod-a':5,'mod-b':8});worker=object.__new__(ContentUpdateWorker);worker.repository=repository;worker.service=service;worker.backend=None;worker.root=ROOT
  result=worker.tick();self.assertEqual(result['updated'],2);self.assertEqual(result['failed'],0);self.assertEqual(repository.claimed,['mod-a','mod-b']);self.assertEqual(repository.completed,[('mod-a',5),('mod-b',8)])
  self.assertEqual([call[4] for call in service.calls],['update','update']);self.assertTrue(all(call[0]=='admin' and call[1]=='content-update-worker' and call[5]=={} for call in service.calls))
 def test_worker_does_not_ack_failed_resolution(self):
  item={'agent_id':'a1','instance_id':'i1','content_id':'mod-a','available_version':'11','assignment_revision':4};repository=_FakeRepository([item]);service=_FakeService({'mod-a':4},fail={'mod-a'});worker=object.__new__(ContentUpdateWorker);worker.repository=repository;worker.service=service;worker.backend=None;worker.root=ROOT
  result=worker.tick();self.assertEqual(result['failed'],1);self.assertEqual(repository.completed,[]);self.assertEqual(repository.failed[0][0],'mod-a')
 def test_worker_refuses_workshop_ack_without_matching_resolved_revision(self):
  item={'agent_id':'a1','instance_id':'i1','content_id':'workshop-a','provider':'steam-workshop','available_version':'101','assignment_revision':4};repository=_FakeRepository([item]);service=_FakeService({'workshop-a':5},versions={'workshop-a':'latest'});worker=object.__new__(ContentUpdateWorker);worker.repository=repository;worker.service=service;worker.backend=None;worker.root=ROOT
  result=worker.tick();self.assertEqual(result['failed'],1);self.assertEqual(repository.completed,[]);self.assertIn('does not match detected upstream revision',repository.failed[0][1])
  repository=_FakeRepository([item]);service=_FakeService({'workshop-a':5},versions={'workshop-a':'101'});worker.repository=repository;worker.service=service
  result=worker.tick();self.assertEqual(result['updated'],1);self.assertEqual(repository.completed,[('workshop-a',5)])
 def test_worker_refuses_structured_ack_without_matching_package_revision(self):
  item={'agent_id':'a1','instance_id':'i1','content_id':'mod-a','provider':'modrinth','available_version':'new-id','assignment_revision':4};repository=_FakeRepository([item]);service=_FakeService({'mod-a':5},artifacts={'mod-a':{'provider':'modrinth','package_id':'project:old-id'}});worker=object.__new__(ContentUpdateWorker);worker.repository=repository;worker.service=service;worker.backend=None;worker.root=ROOT
  result=worker.tick();self.assertEqual(result['failed'],1);self.assertEqual(repository.completed,[]);self.assertIn('structured provider canonical revision',repository.failed[0][1])
  repository=_FakeRepository([item]);service=_FakeService({'mod-a':5},artifacts={'mod-a':{'provider':'modrinth','package_id':'project:new-id'}});worker.repository=repository;worker.service=service
  result=worker.tick();self.assertEqual(result['updated'],1);self.assertEqual(repository.completed,[('mod-a',5)])
 def test_schema_has_dispatch_lease_and_dedupe_fields(self):
  for backend in ('sqlite','postgresql','mysql','mariadb'):
   ddl=content_update_ddl(backend).lower()
   for field in ('dispatched_available_version','dispatched_assignment_revision','dispatch_attempted_at','dispatch_attempted_version','dispatch_attempted_assignment_revision','dispatch_error'):self.assertIn(field,ddl)
 def test_dispatcher_revalidates_canonical_assignment_identity(self):
  text=(ROOT/'database/content_update_dispatch_repository.py').read_text(encoding='utf-8');worker=(ROOT/'dashboard/workers/content_update_worker.py').read_text(encoding='utf-8');supervisor=(ROOT/'dashboard/workers/worker.sh').read_text(encoding='utf-8')
  self.assertIn('a.agent_id=u.agent_id',text);self.assertIn('a.provider=u.provider',text);self.assertIn("current['agent_id']",text);self.assertIn("current['provider']",text);self.assertIn("current['revision']",text);self.assertIn("state='update_available'",text)
  self.assertIn("self.service.mutate(ACTOR,iid,cid,'update',{})",worker);self.assertIn('content update did not create a new canonical revision',worker);self.assertNotIn('self.service.content.put(',worker);self.assertIn('content_update_worker.py',supervisor)


if __name__=='__main__':unittest.main()
