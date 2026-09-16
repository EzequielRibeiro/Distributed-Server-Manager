#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard',ROOT/'dashboard/workers',ROOT/'agents/linux/runtime'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from maintenance_platform import maintenance_event,normalize_pending_work,normalize_policy
from maintenance_worker import MaintenanceWorker

class _Repo:
 def __init__(self):
  policy=normalize_policy({'enabled':True,'warning_offsets_seconds':[],'broadcast_enabled':False,'coalesce_updates':True})
  self.p=policy;self.finished=[]
  self.current={'run_id':'r1','instance_id':'i1','agent_id':'a1','due_at':'2026-09-16T15:00:00Z','status':'pending','stage':'planning','event':maintenance_event(policy,{},pending_work=[{'kind':'game-update','ref':'server','available_version':'101','status':'pending'}]),'warnings_sent':[],'preflight_command_id':None,'save_command_id':None,'stop_command_id':None,'start_command_id':None,'readiness_command_id':None}
 def initialize(self):pass
 def candidates(self,now=None):return []
 def active_runs(self):return [self.current] if self.current['status'] in {'pending','running'} else []
 def policy(self,iid):return self.p
 def run(self,rid):return self.current
 def update_event(self,rid,event,stage=None):self.current['event']=dict(event);self.current['stage']=stage or self.current.get('stage');return self.current
 def set_event(self,rid,event):self.current['event']=dict(event);return self.current
 def _mark(self,key,cid,stage):self.current[key]=cid;self.current['status']='running';self.current['stage']=stage;return self.current
 def mark_preflight(self,rid,cid):return self._mark('preflight_command_id',cid,'preflight')
 def mark_save(self,rid,cid):return self._mark('save_command_id',cid,'saving')
 def mark_stop(self,rid,cid):return self._mark('stop_command_id',cid,'stopping')
 def mark_start(self,rid,cid):return self._mark('start_command_id',cid,'starting')
 def mark_readiness(self,rid,cid):return self._mark('readiness_command_id',cid,'validating')
 def finish(self,rid,success,error_code=None,error_detail=None,now=None):self.finished.append((success,error_code,error_detail));self.current['status']='completed' if success else 'failed';return self.current

class _Automation:
 def initialize(self):pass
 def create_broadcast(self,*args,**kwargs):raise AssertionError('warnings are disabled')

class _Lifecycle:
 def __init__(self):self.enqueued=[];self.states={}
 def initialize(self):pass
 def enqueue(self,**kwargs):
  cid=f"cmd-{len(self.enqueued)+1}";self.enqueued.append((kwargs['action'],cid));self.states[cid]={'command_id':cid,'status':'queued','requested_by':kwargs.get('requested_by')};return self.states[cid]
 def snapshot(self,cid):return self.states[cid]
 def complete(self,cid,payload):self.states[cid]={'command_id':cid,'status':'completed','requested_by':'maintenance-worker','result':{'status':'completed','result':payload}}

class _Game:
 def __init__(self):self.prepared=0;self.finalized=0;self.rolled_back=0
 def discover(self,iid):return []
 def prepare(self,iid,item):
  self.prepared+=1;value=dict(item);value.update(status='activated',job_id='job-prepare',transaction_id='game-update-abc');return value,True
 def finalize(self,iid,item):
  self.finalized+=1;value=dict(item);value.update(status='committed',finalize_job_id='job-finalize');return value,True
 def rollback(self,iid,item):
  self.rolled_back+=1;value=dict(item);value.update(status='rolled_back',rollback_job_id='job-rollback');return value,True

def _worker():
 repo=_Repo();life=_Lifecycle();game=_Game();worker=MaintenanceWorker(None,repository=repo,automation=_Automation(),lifecycle=life,capability_resolver=lambda _: {},content_coordinator=None,game_coordinator=game);return worker,repo,life,game

def _advance_to_doctor(worker,repo,life):
 now=datetime(2026,9,16,15,0,tzinfo=timezone.utc)
 worker.tick(now=now);pre=repo.current['preflight_command_id'];life.complete(pre,{'observed_state':'running'})
 worker.tick(now=now);stop=repo.current['stop_command_id'];life.complete(stop,{'observed_state':'stopped'})
 worker.tick(now=now);start=repo.current['start_command_id'];life.complete(start,{'observed_state':'running'})
 worker.tick(now=now);doctor=repo.current['readiness_command_id'];return now,doctor

class MaintenanceGameUpdateCoalescingTest(unittest.TestCase):
 def test_success_commits_only_after_readiness_and_uses_one_stop_start(self):
  worker,repo,life,game=_worker();now,doctor=_advance_to_doctor(worker,repo,life)
  self.assertEqual(game.prepared,1);self.assertEqual(game.finalized,0);self.assertEqual([a for a,_ in life.enqueued],['status','stop','start','doctor'])
  life.complete(doctor,{'ready':True});worker.tick(now=now)
  self.assertEqual(game.finalized,1);self.assertEqual(game.rolled_back,0);self.assertEqual(repo.finished,[(True,None,None)]);self.assertEqual([a for a,_ in life.enqueued].count('stop'),1);self.assertEqual([a for a,_ in life.enqueued].count('start'),1)
 def test_readiness_failure_rolls_back_then_recovers_old_runtime(self):
  worker,repo,life,game=_worker();now,doctor=_advance_to_doctor(worker,repo,life);life.complete(doctor,{'ready':False});worker.tick(now=now)
  self.assertEqual(game.finalized,0);self.assertEqual(repo.current['event']['recovery']['phase'],'stop')
  worker.tick(now=now);recovery_stop=repo.current['event']['recovery']['stop_command_id'];life.complete(recovery_stop,{'observed_state':'stopped'});worker.tick(now=now)
  self.assertEqual(repo.current['event']['recovery']['phase'],'rollback');worker.tick(now=now);self.assertEqual(game.rolled_back,1);self.assertEqual(repo.current['event']['recovery']['phase'],'start')
  worker.tick(now=now);recovery_start=repo.current['event']['recovery']['start_command_id'];life.complete(recovery_start,{'observed_state':'running'});worker.tick(now=now);self.assertEqual(repo.current['event']['recovery']['phase'],'doctor')
  worker.tick(now=now);recovery_doctor=repo.current['event']['recovery']['readiness_command_id'];life.complete(recovery_doctor,{'ready':True});worker.tick(now=now)
  self.assertFalse(repo.finished[-1][0]);self.assertEqual(repo.finished[-1][1],'readiness_failed_rolled_back');self.assertEqual([a for a,_ in life.enqueued],['status','stop','start','doctor','stop','start','doctor'])
 def test_pending_work_only_preserves_opaque_safe_transaction_tokens(self):
  values=normalize_pending_work([{'kind':'game-update','ref':'server','status':'activated','job_id':'game-data-1','transaction_id':'game-update-abc','finalize_job_id':'game-data-2','rollback_job_id':'../../etc/passwd'}]);self.assertEqual(values[0]['transaction_id'],'game-update-abc');self.assertEqual(values[0]['finalize_job_id'],'game-data-2');self.assertNotIn('rollback_job_id',values[0])
 def test_agent_transaction_is_state_root_owned_and_fail_closed_for_shared_running_instances(self):
  text=(ROOT/'agents/linux/runtime/maintenance_game_update.py').read_text(encoding='utf-8');executor=(ROOT/'agents/linux/runtime/game_data_executor.py').read_text(encoding='utf-8');repo=(ROOT/'database/agent_game_data_repository.py').read_text(encoding='utf-8')
  self.assertIn('STATE_ROOT / "server-update-maintenance"',text);self.assertIn('_all_stopped(config,affected)',text.replace(' ',''));self.assertIn('shared game-data maintenance requires every affected instance stopped',text);self.assertNotIn('shell=True',text);self.assertNotIn('os.system(',text)
  self.assertIn('MAINTENANCE_ACTIONS',executor);self.assertIn('maintenance_game_update',executor);self.assertIn('MAINTENANCE_ACTIONS',repo);self.assertIn('not in MAINTENANCE_ACTIONS',repo)

if __name__=='__main__':unittest.main()
