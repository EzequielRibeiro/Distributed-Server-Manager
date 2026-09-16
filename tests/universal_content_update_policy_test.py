#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard',ROOT/'dashboard/workers'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from content_update_dispatch_repository import ContentUpdateDispatchRepository
from server_update_schema import content_update_ddl
from content_update_worker import ContentUpdateWorker


class _FakeRepository:
 def __init__(self,items):self.items=list(items);self.claimed=[];self.completed=[];self.failed=[]
 def initialize(self):return None
 def due(self,limit=200):return list(self.items)[:limit]
 def claim(self,item):self.claimed.append(item['content_id']);return True
 def complete(self,item,revision):self.completed.append((item['content_id'],revision))
 def fail(self,item,error):self.failed.append((item['content_id'],str(error)))


class _FakeContent:
 def __init__(self,revisions):self.revisions=dict(revisions)
 def get(self,instance_id,content_id):return {'instance_id':instance_id,'content_id':content_id,'revision':self.revisions[content_id]}


class _FakeService:
 def __init__(self,revisions,fail=None):self.content=_FakeContent(revisions);self.calls=[];self.fail=set(fail or [])
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
 def test_worker_routes_updates_through_canonical_u9_service(self):
  items=[{'agent_id':'a1','instance_id':'i1','content_id':'mod-a','available_version':'11','assignment_revision':4},{'agent_id':'a1','instance_id':'i1','content_id':'mod-b','available_version':'22','assignment_revision':7}]
  repository=_FakeRepository(items);service=_FakeService({'mod-a':5,'mod-b':8});worker=object.__new__(ContentUpdateWorker);worker.repository=repository;worker.service=service;worker.backend=None;worker.root=ROOT
  result=worker.tick();self.assertEqual(result['updated'],2);self.assertEqual(result['failed'],0);self.assertEqual(repository.claimed,['mod-a','mod-b']);self.assertEqual(repository.completed,[('mod-a',5),('mod-b',8)])
  self.assertEqual([call[4] for call in service.calls],['update','update']);self.assertTrue(all(call[0]=='admin' and call[1]=='content-update-worker' and call[5]=={} for call in service.calls))
 def test_worker_does_not_ack_failed_resolution(self):
  item={'agent_id':'a1','instance_id':'i1','content_id':'mod-a','available_version':'11','assignment_revision':4};repository=_FakeRepository([item]);service=_FakeService({'mod-a':4},fail={'mod-a'});worker=object.__new__(ContentUpdateWorker);worker.repository=repository;worker.service=service;worker.backend=None;worker.root=ROOT
  result=worker.tick();self.assertEqual(result['failed'],1);self.assertEqual(repository.completed,[]);self.assertEqual(repository.failed[0][0],'mod-a')
 def test_schema_has_dispatch_lease_and_dedupe_fields(self):
  for backend in ('sqlite','postgresql','mysql','mariadb'):
   ddl=content_update_ddl(backend).lower()
   for field in ('dispatched_available_version','dispatched_assignment_revision','dispatch_attempted_at','dispatch_attempted_version','dispatch_attempted_assignment_revision','dispatch_error'):self.assertIn(field,ddl)
 def test_dispatcher_revalidates_canonical_assignment_identity(self):
  text=(ROOT/'database/content_update_dispatch_repository.py').read_text(encoding='utf-8');worker=(ROOT/'dashboard/workers/content_update_worker.py').read_text(encoding='utf-8');supervisor=(ROOT/'dashboard/workers/worker.sh').read_text(encoding='utf-8')
  self.assertIn('a.agent_id=u.agent_id',text);self.assertIn("current['agent_id']",text);self.assertIn("current['revision']",text);self.assertIn("state='update_available'",text)
  self.assertIn("self.service.mutate(ACTOR,iid,cid,'update',{})",worker);self.assertNotIn('self.service.content.put(',worker);self.assertIn('content_update_worker.py',supervisor)


if __name__=='__main__':unittest.main()
