#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard',ROOT/'dashboard/workers'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from content_update_dispatch_repository import ContentUpdateDispatchRepository
from maintenance_content_coordinator import MaintenanceContentCoordinator
from maintenance_platform import normalize_policy
from maintenance_worker import MaintenanceWorker


def _update_row(**overrides):
 row={'agent_id':'a1','instance_id':'i1','content_id':'steam-workshop:100','provider':'steam-workshop','content_type':'workshop','installed_version':'100','available_version':'101','dispatched_available_version':None,'dispatched_assignment_revision':None,'dispatch_attempted_at':None,'dispatch_attempted_version':None,'dispatch_attempted_assignment_revision':None,'dispatch_error':None,'assignment_revision':1,'assignment_checksum':'abc','desired_state':'installed','override_mode':'inherit','instance_mode':'maintenance','instance_timezone':'UTC','instance_weekdays_json':'[0,1,2,3,4,5,6]','instance_start_time':'00:00','instance_duration_minutes':720,'instance_check_interval_seconds':900,'instance_backup_before_update':1,'maintenance_enabled':1,'maintenance_coalesce_updates':1}
 row.update(overrides);return row

class _RowsDispatch(ContentUpdateDispatchRepository):
 def __init__(self,rows):self.rows=rows
 def _rows(self,**kwargs):
  iid=kwargs.get('instance_id');return [dict(row) for row in self.rows if iid is None or str(row.get('instance_id'))==str(iid)]

class _CoordinatorDispatch:
 def __init__(self):self.completed=[];self.failed=[];self.claims=0
 def due_for_maintenance(self,iid,limit=200):return [_update_row()]
 def claim(self,item):self.claims+=1;return True
 def complete(self,item,revision):self.completed.append((item['content_id'],revision))
 def fail(self,item,error):self.failed.append(str(error))
 def alignment(self,iid,expected):return {'ready':True,'pending':[],'failed':[],'aligned':list(expected)}
class _ContentStore:
 def get(self,iid,cid):return {'revision':2,'version':'101','artifact':{},'provider':'steam-workshop'}
class _Service:
 def __init__(self):self.content=_ContentStore();self.calls=[]
 def mutate(self,user,iid,cid,action,body):self.calls.append((iid,cid,action))

class _Repo:
 def __init__(self):
  self.p=normalize_policy({'enabled':True,'coalesce_updates':True,'warning_offsets_seconds':[]});self.current={'run_id':'r1','instance_id':'i1','agent_id':'a1','due_at':'2026-09-16T15:00:00Z','status':'pending','stage':'planning','event':{},'warnings_sent':[],'preflight_command_id':None,'save_command_id':None,'stop_command_id':None,'start_command_id':None,'readiness_command_id':None};self.finished=[]
 def initialize(self):pass
 def candidates(self,now=None):return []
 def ensure_run(self,iid,now=None):return None
 def active_runs(self):return [dict(self.current)] if self.current['status'] in {'pending','running'} else []
 def policy(self,iid):return dict(self.p)
 def set_event(self,rid,event):self.current['event']=dict(event);self.current['stage']='warning';return dict(self.current)
 def update_event(self,rid,event,stage=None):self.current['event']=dict(event);self.current['stage']=stage or self.current['stage'];return dict(self.current)
 def run(self,rid):return dict(self.current)
 def _mark(self,key,cid,stage):self.current[key]=cid;self.current['status']='running';self.current['stage']=stage;return dict(self.current)
 def mark_preflight(self,rid,cid):return self._mark('preflight_command_id',cid,'preflight')
 def mark_save(self,rid,cid):return self._mark('save_command_id',cid,'saving')
 def mark_stop(self,rid,cid):return self._mark('stop_command_id',cid,'stopping')
 def mark_start(self,rid,cid):return self._mark('start_command_id',cid,'starting')
 def mark_readiness(self,rid,cid):return self._mark('readiness_command_id',cid,'validating')
 def record_warning(self,*args,**kwargs):return dict(self.current)
 def finish(self,rid,success,error_code=None,error_detail=None,now=None):self.finished.append((success,error_code));self.current['status']='completed' if success else 'failed';return dict(self.current)
class _Automation:
 def initialize(self):pass
 def create_broadcast(self,*args,**kwargs):return {'broadcast_id':'b1'}
class _Lifecycle:
 def __init__(self):self.enqueued=[];self.states={}
 def initialize(self):pass
 def enqueue(self,**kwargs):
  self.enqueued.append(kwargs);cid=f"cmd-{len(self.enqueued)}";self.states[cid]={'command_id':cid,'status':'queued','requested_by':kwargs.get('requested_by')};return self.states[cid]
 def snapshot(self,cid):return self.states[cid]
 def complete(self,cid,payload):self.states[cid]={'command_id':cid,'status':'completed','requested_by':'maintenance-worker','result':{'status':'completed','result':payload}}
class _CoalescedContent:
 def __init__(self):self.align_calls=0;self.dispatch_calls=0
 def discover(self,iid):return [{'kind':'content-update','ref':'steam-workshop:100','available_version':'101','status':'pending'}]
 def dispatch_pending(self,iid,work):
  self.dispatch_calls+=1;out=[]
  for raw in work:
   item=dict(raw)
   if item.get('kind')=='content-update' and not item.get('desired_revision'):item['desired_revision']=2;item['status']='dispatched'
   out.append(item)
  return out
 def alignment(self,iid,work):
  self.align_calls+=1;items=[dict(x) for x in work]
  if self.align_calls==1:return {'ready':False,'pending':['steam-workshop:100'],'failed':[],'aligned':[],'work':items}
  for item in items:
   if item.get('kind')=='content-update':item['status']='aligned'
  return {'ready':True,'pending':[],'failed':[],'aligned':['steam-workshop:100'],'work':items}

class MaintenanceContentCoalescingTest(unittest.TestCase):
 def test_m4_worker_defers_coalesced_maintenance_item(self):
  repo=_RowsDispatch([_update_row()]);now=datetime(2026,9,16,10,0,tzinfo=timezone.utc)
  self.assertEqual(repo.due(now=now),[])
  reserved=repo.due_for_maintenance('i1');self.assertEqual(len(reserved),1);self.assertEqual(reserved[0]['effective_mode'],'maintenance')
 def test_explicit_maintenance_override_still_requires_instance_update_policy(self):
  row=_update_row(override_mode='maintenance',instance_mode=None);repo=_RowsDispatch([row]);self.assertEqual(repo.due_for_maintenance('i1'),[])
 def test_coordinator_creates_and_validates_canonical_revision(self):
  coordinator=object.__new__(MaintenanceContentCoordinator);coordinator.dispatch=_CoordinatorDispatch();coordinator.service=_Service();work=coordinator.discover('i1');updated=coordinator.dispatch_pending('i1',work)
  self.assertEqual(updated[0]['desired_revision'],2);self.assertEqual(updated[0]['status'],'dispatched');self.assertEqual(coordinator.dispatch.completed,[('steam-workshop:100',2)]);self.assertEqual(coordinator.service.calls,[('i1','steam-workshop:100','update')])
  aligned=coordinator.alignment('i1',updated);self.assertTrue(aligned['ready']);self.assertEqual(aligned['work'][0]['status'],'aligned')
 def test_worker_waits_for_content_alignment_before_single_start(self):
  repo=_Repo();life=_Lifecycle();content=_CoalescedContent();worker=MaintenanceWorker(None,repository=repo,automation=_Automation(),lifecycle=life,capability_resolver=lambda _: {},content_coordinator=content);now=datetime(2026,9,16,15,0,tzinfo=timezone.utc)
  worker.tick(now=now);self.assertEqual([x['action'] for x in life.enqueued],['status']);life.complete(repo.current['preflight_command_id'],{'observed_state':'running'})
  worker.tick(now=now);self.assertEqual([x['action'] for x in life.enqueued],['status','stop']);life.complete(repo.current['stop_command_id'],{'observed_state':'stopped'})
  first=worker.tick(now=now);self.assertEqual(first['content_dispatched'],1);self.assertGreater(first['content_waiting'],0);self.assertEqual([x['action'] for x in life.enqueued],['status','stop'])
  second=worker.tick(now=now);self.assertEqual(second['content_aligned'],1);self.assertEqual([x['action'] for x in life.enqueued],['status','stop','start']);self.assertEqual(content.dispatch_calls,2)
 def test_agent_content_paths_do_not_restart_when_maintenance_has_already_stopped_instance(self):
  client=(ROOT/'agents/linux/runtime/content_client.py').read_text();activation=(ROOT/'agents/linux/runtime/content_activation_apply.py').read_text()
  self.assertIn('was_running=instance_runtime.status(config,iid).get("observed_state")=="running"',client)
  self.assertIn('was_running=instance_runtime.status(config,iid).get("observed_state")=="running"',activation)
  self.assertRegex(client,r'if was_running:\s*\n\s*instance_runtime\.lifecycle\(config,iid,"start"\)')
  self.assertIn('if was_running:',activation)

if __name__=='__main__':unittest.main()
