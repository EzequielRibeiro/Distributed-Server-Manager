#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard',ROOT/'dashboard/workers'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from maintenance_platform import MaintenanceValidationError,due_warning_offsets,maintenance_event,next_due_at,normalize_capabilities,normalize_policy,render_warning
from maintenance_schema import maintenance_ddl
from maintenance_worker import MaintenanceWorker

class _Repo:
 def __init__(self,run=None,policy=None):self.current=run;self.p=policy or normalize_policy({'enabled':True,'warning_offsets_seconds':[60]});self.warnings=[];self.commands=[];self.finished=[]
 def initialize(self):pass
 def candidates(self,now=None):return []
 def ensure_run(self,iid,now=None):return None
 def active_runs(self):return [self.current] if self.current and self.current.get('status') in {'pending','running'} else []
 def run(self,rid):return self.current
 def policy(self,iid):return self.p
 def set_event(self,rid,event):self.current['event']=event;self.current['stage']='warning';return self.current
 def record_warning(self,rid,offset,bid):self.warnings.append((offset,bid));self.current['warnings_sent']=sorted(set(self.current.get('warnings_sent',[])+[offset]),reverse=True);return self.current
 def _mark(self,key,cid,stage):self.commands.append((key,cid));self.current[key]=cid;self.current['status']='running';self.current['stage']=stage;return self.current
 def mark_preflight(self,rid,cid):return self._mark('preflight_command_id',cid,'preflight')
 def mark_save(self,rid,cid):return self._mark('save_command_id',cid,'saving')
 def mark_stop(self,rid,cid):return self._mark('stop_command_id',cid,'stopping')
 def mark_start(self,rid,cid):return self._mark('start_command_id',cid,'starting')
 def mark_readiness(self,rid,cid):return self._mark('readiness_command_id',cid,'validating')
 def finish(self,rid,success,error_code=None,error_detail=None,now=None,next_due_override=None):self.finished.append((success,error_code,error_detail,next_due_override));self.current['status']='completed' if success else 'failed';return self.current
class _Automation:
 def __init__(self):self.items=[]
 def initialize(self):pass
 def create_broadcast(self,body,requested_by=None):self.items.append((body,requested_by));return {'broadcast_id':f'b-{len(self.items)}'}
class _Lifecycle:
 def __init__(self):self.enqueued=[];self.states={}
 def initialize(self):pass
 def enqueue(self,**kwargs):
  self.enqueued.append(kwargs);cid=f"cmd-{len(self.enqueued)}";self.states[cid]={'command_id':cid,'status':'queued','requested_by':kwargs.get('requested_by')};return self.states[cid]
 def snapshot(self,cid):return self.states[cid]
def _complete(life,cid,payload=None):life.states[cid]={'command_id':cid,'status':'completed','requested_by':'maintenance-worker','result':{'status':'completed','result':payload or {}}}
def _run():return {'run_id':'r1','instance_id':'i1','agent_id':'a1','due_at':'2026-09-16T15:00:00Z','status':'pending','stage':'planning','event':{},'warnings_sent':[],'preflight_command_id':None,'save_command_id':None,'stop_command_id':None,'start_command_id':None,'readiness_command_id':None}

class MaintenanceRestartFrameworkTest(unittest.TestCase):
 def test_disabled_by_default_and_validation_is_fail_closed(self):
  policy=normalize_policy({});self.assertFalse(policy['enabled']);self.assertEqual(policy['schedule_mode'],'fixed');self.assertTrue(policy['coalesce_updates'])
  with self.assertRaises(MaintenanceValidationError):normalize_policy({'timezone':'../bad'})
  with self.assertRaises(MaintenanceValidationError):normalize_policy({'warning_template':'{shell}'})
  with self.assertRaises(MaintenanceValidationError):normalize_policy({'schedule_mode':'interval','interval_seconds':3600,'warning_offsets_seconds':[3600]})
  interval=normalize_policy({'schedule_mode':'interval','interval_seconds':3600,'timezone':'../bad','start_time':'99:99','weekdays':[],'warning_offsets_seconds':[1800,300,60]})
  self.assertEqual(interval['timezone'],'UTC');self.assertEqual(interval['start_time'],'04:00');self.assertEqual(interval['weekdays'],list(range(7)))
 def test_fixed_schedule_resolves_dst_gap_to_first_valid_wall_time(self):
  policy={'enabled':True,'schedule_mode':'fixed','timezone':'America/New_York','weekdays':[6],'start_time':'02:30','warning_offsets_seconds':[]};now=datetime(2026,3,8,6,50,tzinfo=timezone.utc);self.assertEqual(next_due_at(policy,now=now),datetime(2026,3,8,7,0,tzinfo=timezone.utc))
 def test_interval_uses_completion_anchor_without_immediate_restart(self):
  policy={'enabled':True,'schedule_mode':'interval','interval_seconds':21600,'warning_offsets_seconds':[3600]};anchor=datetime(2026,9,16,12,0,tzinfo=timezone.utc);self.assertEqual(next_due_at(policy,now=anchor,anchor=anchor),datetime(2026,9,16,18,0,tzinfo=timezone.utc))
 def test_capabilities_fail_closed_except_lifecycle_restart(self):
  caps=normalize_capabilities({});self.assertTrue(caps['scheduled_restart']);self.assertFalse(caps['broadcast']);self.assertFalse(caps['save']);self.assertFalse(caps['graceful_shutdown'])
  event=maintenance_event({'enabled':True,'broadcast_enabled':True},caps);self.assertFalse(event['warnings_enabled']);self.assertEqual(event['steps'],['preflight','stop','start','readiness'])
  event=maintenance_event({'enabled':True,'broadcast_enabled':True},{'broadcast':{'supported':True},'graceful_save':{'supported':True}});self.assertTrue(event['warnings_enabled']);self.assertEqual(event['steps'],['warning','preflight','save','stop','start','readiness'])
 def test_warning_offsets_are_idempotent_and_human_readable(self):
  policy={'enabled':True,'warning_offsets_seconds':[300,60]};due=datetime(2026,9,16,15,0,tzinfo=timezone.utc);now=datetime(2026,9,16,14,59,tzinfo=timezone.utc);self.assertEqual(due_warning_offsets(policy,due,now=now,sent_offsets={300}),[60]);self.assertEqual(render_warning(policy,60),'Servidor será reiniciado em 1 minuto.')
 def test_schema_parity(self):
  for backend in ('sqlite','postgresql','mysql','mariadb'):
   ddl=maintenance_ddl(backend).lower()
   for table in ('instance_maintenance_policy','instance_maintenance_state','instance_maintenance_runs'):self.assertIn('create table '+table,ddl)
   for column in ('event_json','preflight_command_id','save_command_id','stop_command_id','start_command_id','readiness_command_id'):self.assertIn(column,ddl)
 def test_worker_warns_then_preflight_stop_start_doctor_without_restart_action(self):
  repo=_Repo(_run());auto=_Automation();life=_Lifecycle();worker=MaintenanceWorker(None,repository=repo,automation=auto,lifecycle=life,capability_resolver=lambda _: {'broadcast':True})
  worker.tick(now=datetime(2026,9,16,14,59,tzinfo=timezone.utc));self.assertEqual(len(auto.items),1);worker.tick(now=datetime(2026,9,16,14,59,30,tzinfo=timezone.utc));self.assertEqual(len(auto.items),1)
  worker.tick(now=datetime(2026,9,16,15,0,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['status']);pre=repo.current['preflight_command_id'];_complete(life,pre,{'observed_state':'running'})
  worker.tick(now=datetime(2026,9,16,15,0,5,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['status','stop']);stop=repo.current['stop_command_id'];_complete(life,stop,{'observed_state':'stopped'})
  worker.tick(now=datetime(2026,9,16,15,0,10,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['status','stop','start']);start=repo.current['start_command_id'];_complete(life,start,{'observed_state':'running'})
  worker.tick(now=datetime(2026,9,16,15,0,15,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['status','stop','start','doctor']);doctor=repo.current['readiness_command_id'];_complete(life,doctor,{'ready':True})
  worker.tick(now=datetime(2026,9,16,15,0,20,tzinfo=timezone.utc));self.assertEqual(repo.finished,[(True,None,None,None)]);self.assertNotIn('restart',[x['action'] for x in life.enqueued])
 def test_success_uses_prepared_native_restart_due_as_next_schedule_anchor(self):
  run=_run();run.update({'status':'running','event':maintenance_event({'enabled':True},{'native_countdown':{'supported':True}}),'preflight_command_id':'pre','start_command_id':'start','readiness_command_id':'doctor'})
  run['event']['native_restart']={'command_id':'native-1','due_at':'2026-09-16T16:00:00Z','status':'completed'}
  repo=_Repo(run);life=_Lifecycle();_complete(life,'pre',{'observed_state':'stopped'});_complete(life,'start',{'observed_state':'running'});_complete(life,'doctor',{'ready':True})
  worker=MaintenanceWorker(None,repository=repo,automation=_Automation(),lifecycle=life,capability_resolver=lambda _: {'native_countdown':{'supported':True}})
  worker.tick(now=datetime(2026,9,16,15,1,tzinfo=timezone.utc))
  self.assertEqual(repo.finished[0][3],'2026-09-16T16:00:00Z')

 def test_save_is_only_enqueued_when_runtime_declares_support(self):
  repo=_Repo(_run());life=_Lifecycle();worker=MaintenanceWorker(None,repository=repo,automation=_Automation(),lifecycle=life,capability_resolver=lambda _: {'save':True})
  worker.tick(now=datetime(2026,9,16,15,0,tzinfo=timezone.utc));pre=repo.current['preflight_command_id'];_complete(life,pre,{'observed_state':'running'});worker.tick(now=datetime(2026,9,16,15,0,1,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['status','save']);save=repo.current['save_command_id'];_complete(life,save,{});worker.tick(now=datetime(2026,9,16,15,0,2,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['status','save','stop'])
 def test_stopped_instance_is_not_started_by_scheduled_maintenance(self):
  repo=_Repo(_run());life=_Lifecycle();worker=MaintenanceWorker(None,repository=repo,automation=_Automation(),lifecycle=life,capability_resolver=lambda _: {})
  worker.tick(now=datetime(2026,9,16,15,0,tzinfo=timezone.utc));pre=repo.current['preflight_command_id'];_complete(life,pre,{'observed_state':'stopped'});report=worker.tick(now=datetime(2026,9,16,15,0,1,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['status']);self.assertEqual(report['skipped'],1);self.assertTrue(repo.finished[0][0])
 def test_save_failure_aborts_before_stop(self):
  repo=_Repo(_run());life=_Lifecycle();worker=MaintenanceWorker(None,repository=repo,automation=_Automation(),lifecycle=life,capability_resolver=lambda _: {'save':True})
  worker.tick(now=datetime(2026,9,16,15,0,tzinfo=timezone.utc));_complete(life,repo.current['preflight_command_id'],{'observed_state':'running'});worker.tick(now=datetime(2026,9,16,15,0,1,tzinfo=timezone.utc));sid=repo.current['save_command_id'];life.states[sid]={'command_id':sid,'status':'failed','last_error':'save failed','requested_by':'maintenance-worker'};worker.tick(now=datetime(2026,9,16,15,0,2,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['status','save']);self.assertEqual(repo.finished[0][1],'save_failed')
 def test_readiness_failure_fails_run(self):
  run=_run();run.update({'status':'running','event':maintenance_event({'enabled':True},{}),'preflight_command_id':'pre','stop_command_id':'stop','start_command_id':'start','readiness_command_id':'doctor'});repo=_Repo(run);life=_Lifecycle();_complete(life,'pre',{'observed_state':'running'});_complete(life,'stop',{'observed_state':'stopped'});_complete(life,'start',{'observed_state':'running'});_complete(life,'doctor',{'ready':False});worker=MaintenanceWorker(None,repository=repo,automation=_Automation(),lifecycle=life,capability_resolver=lambda _: {});worker.tick(now=datetime(2026,9,16,15,1,tzinfo=timezone.utc));self.assertFalse(repo.finished[0][0]);self.assertEqual(repo.finished[0][1],'readiness_failed')
 def test_typed_save_exists_on_both_agents_and_is_serialized(self):
  repository=(ROOT/'database/agent_instance_runtime_repository.py').read_text();linux=(ROOT/'agents/linux/runtime/instance_runtime.py').read_text();windows=(ROOT/'agents/windows/runtime/instance_runtime.py').read_text();linux_base=(ROOT/'agents/linux/runtime/adapters/base.py').read_text();windows_base=(ROOT/'agents/windows/runtime/adapters/base.py').read_text()
  self.assertIn('SERIALIZED_ACTIONS = {"save"',repository)
  for text in (linux,windows):self.assertIn('"save"',text);self.assertIn('maintenance:save',text);self.assertNotIn('shell=True',text)
  for text in (linux_base,windows_base):self.assertIn('def save(',text)
 def test_baseline_and_supervisor_are_wired(self):
  baseline=(ROOT/'database/schema_baseline.py').read_text();worker=(ROOT/'dashboard/workers/worker.sh').read_text();self.assertIn('ensure_maintenance_schema',baseline);self.assertIn('start_python_worker maintenance_worker.py',worker)

if __name__=='__main__':unittest.main()
