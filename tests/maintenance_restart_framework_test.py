#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard/workers'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from maintenance_platform import MaintenanceValidationError,due_warning_offsets,next_due_at,normalize_policy,render_warning
from maintenance_schema import maintenance_ddl
from maintenance_worker import MaintenanceWorker

class _Repo:
 def __init__(self,run=None,policy=None):self.current=run;self.p=policy or normalize_policy({'enabled':True,'warning_offsets_seconds':[60]});self.warnings=[];self.restarts=[];self.readiness=[];self.finished=[]
 def initialize(self):pass
 def candidates(self,now=None):return []
 def ensure_run(self,iid,now=None):return None
 def active_runs(self):return [self.current] if self.current and self.current.get('status') in {'pending','running'} else []
 def policy(self,iid):return self.p
 def record_warning(self,rid,offset,bid):self.warnings.append((offset,bid));self.current['warnings_sent']=sorted(set(self.current.get('warnings_sent',[])+[offset]),reverse=True);return self.current
 def mark_restart(self,rid,cid):self.restarts.append(cid);self.current['lifecycle_command_id']=cid;self.current['status']='running';self.current['stage']='restarting';return self.current
 def mark_readiness(self,rid,cid):self.readiness.append(cid);self.current['readiness_command_id']=cid;self.current['stage']='validating';return self.current
 def finish(self,rid,success,error_code=None,error_detail=None,now=None):self.finished.append((success,error_code,error_detail));self.current['status']='completed' if success else 'failed';return self.current
class _Automation:
 def __init__(self):self.items=[]
 def initialize(self):pass
 def create_broadcast(self,body,requested_by=None):self.items.append((body,requested_by));return {'broadcast_id':f'b-{len(self.items)}'}
class _Lifecycle:
 def __init__(self):self.enqueued=[];self.states={}
 def initialize(self):pass
 def enqueue(self,**kwargs):
  self.enqueued.append(kwargs);cid=f"cmd-{len(self.enqueued)}";self.states[cid]={'command_id':cid,'status':'queued'};return self.states[cid]
 def snapshot(self,cid):return self.states[cid]

class MaintenanceRestartFrameworkTest(unittest.TestCase):
 def test_disabled_by_default_and_validation_is_fail_closed(self):
  policy=normalize_policy({});self.assertFalse(policy['enabled']);self.assertEqual(policy['schedule_mode'],'fixed');self.assertTrue(policy['coalesce_updates'])
  with self.assertRaises(MaintenanceValidationError):normalize_policy({'timezone':'../bad'})
  with self.assertRaises(MaintenanceValidationError):normalize_policy({'warning_template':'{shell}'})
  with self.assertRaises(MaintenanceValidationError):normalize_policy({'schedule_mode':'interval','interval_seconds':3600,'warning_offsets_seconds':[3600]})
 def test_fixed_schedule_resolves_dst_gap_to_first_valid_wall_time(self):
  policy={'enabled':True,'schedule_mode':'fixed','timezone':'America/New_York','weekdays':[6],'start_time':'02:30','warning_offsets_seconds':[]}
  now=datetime(2026,3,8,6,50,tzinfo=timezone.utc);self.assertEqual(next_due_at(policy,now=now),datetime(2026,3,8,7,0,tzinfo=timezone.utc))
 def test_interval_uses_completion_anchor_without_immediate_restart(self):
  policy={'enabled':True,'schedule_mode':'interval','interval_seconds':21600,'warning_offsets_seconds':[3600]};anchor=datetime(2026,9,16,12,0,tzinfo=timezone.utc)
  self.assertEqual(next_due_at(policy,now=anchor,anchor=anchor),datetime(2026,9,16,18,0,tzinfo=timezone.utc))
 def test_warning_offsets_are_idempotent_and_human_readable(self):
  policy={'enabled':True,'warning_offsets_seconds':[300,60]};due=datetime(2026,9,16,15,0,tzinfo=timezone.utc);now=datetime(2026,9,16,14,59,tzinfo=timezone.utc)
  self.assertEqual(due_warning_offsets(policy,due,now=now,sent_offsets={300}),[60]);self.assertEqual(render_warning(policy,60),'Servidor será reiniciado em 1 minuto.')
 def test_schema_parity(self):
  for backend in ('sqlite','postgresql','mysql','mariadb'):
   ddl=maintenance_ddl(backend).lower()
   for table in ('instance_maintenance_policy','instance_maintenance_state','instance_maintenance_runs'):self.assertIn('create table '+table,ddl)
   self.assertIn('readiness_command_id',ddl)
 def test_worker_sends_warning_once_then_one_restart_then_doctor(self):
  due='2026-09-16T15:00:00Z';run={'run_id':'r1','instance_id':'i1','agent_id':'a1','due_at':due,'status':'pending','stage':'warning','warnings_sent':[],'lifecycle_command_id':None,'readiness_command_id':None};repo=_Repo(run);auto=_Automation();life=_Lifecycle();worker=MaintenanceWorker(None,repository=repo,automation=auto,lifecycle=life)
  worker.tick(now=datetime(2026,9,16,14,59,tzinfo=timezone.utc));self.assertEqual(len(auto.items),1);self.assertEqual(repo.current['warnings_sent'],[60]);worker.tick(now=datetime(2026,9,16,14,59,30,tzinfo=timezone.utc));self.assertEqual(len(auto.items),1)
  worker.tick(now=datetime(2026,9,16,15,0,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['restart']);restart_id=repo.current['lifecycle_command_id'];worker.tick(now=datetime(2026,9,16,15,0,5,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['restart'])
  life.states[restart_id]={'command_id':restart_id,'status':'completed','result':{'status':'completed','result':{'observed_state':'running'}}};worker.tick(now=datetime(2026,9,16,15,0,10,tzinfo=timezone.utc));self.assertEqual([x['action'] for x in life.enqueued],['restart','doctor']);doctor_id=repo.current['readiness_command_id']
  life.states[doctor_id]={'command_id':doctor_id,'status':'completed','result':{'status':'completed','result':{'ready':True}}};worker.tick(now=datetime(2026,9,16,15,0,15,tzinfo=timezone.utc));self.assertEqual(repo.finished,[(True,None,None)]);self.assertEqual([x['action'] for x in life.enqueued].count('restart'),1)
 def test_readiness_failure_fails_run(self):
  run={'run_id':'r2','instance_id':'i1','agent_id':'a1','due_at':'2026-09-16T15:00:00Z','status':'running','stage':'validating','warnings_sent':[],'lifecycle_command_id':'restart','readiness_command_id':'doctor'};repo=_Repo(run);auto=_Automation();life=_Lifecycle();life.states['restart']={'status':'completed','result':{'status':'completed','result':{}}};life.states['doctor']={'status':'completed','result':{'status':'completed','result':{'ready':False}}};worker=MaintenanceWorker(None,repository=repo,automation=auto,lifecycle=life);worker.tick(now=datetime(2026,9,16,15,1,tzinfo=timezone.utc));self.assertFalse(repo.finished[0][0]);self.assertEqual(repo.finished[0][1],'readiness_failed')
 def test_baseline_and_supervisor_are_wired(self):
  baseline=(ROOT/'database/schema_baseline.py').read_text();worker=(ROOT/'dashboard/workers/worker.sh').read_text();self.assertIn('ensure_maintenance_schema',baseline);self.assertIn('start_python_worker maintenance_worker.py',worker)

if __name__=='__main__':unittest.main()
