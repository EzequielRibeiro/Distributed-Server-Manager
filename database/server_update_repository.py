#!/usr/bin/env python3
"""Persistence, scheduling and game-data reconciliation for server updates."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
import json,uuid
from typing import Any,Iterator
from alert_repository import AlertSession,dialect_for_backend
from core.agent_health import utc_timestamp
from core.server_update_platform import normalize_policy,should_apply
from agent_game_data_repository import AgentGameDataRepository

def _parse(value:Any)->datetime|None:
 try:return datetime.fromisoformat(str(value).replace('Z','+00:00'))
 except Exception:return None

class ServerUpdateRepository:
 def __init__(self,backend):self.backend=backend;self.dialect=dialect_for_backend(backend)
 def initialize(self):return self.backend.initialize()
 @contextmanager
 def session(self,transaction:bool=False)->Iterator[AlertSession]:
  ctx=self.backend.transaction() if transaction else self.backend.connect()
  with ctx as c:
   s=AlertSession(self.backend,c)
   try:yield s
   finally:s.close()
 def set_policy(self,*,instance_id:str,agent_id:str,selection:dict[str,Any],policy:dict[str,Any],requested_by:str|None=None)->dict[str,Any]:
  iid=str(instance_id or '').strip();aid=str(agent_id or '').strip()
  if not iid or not aid:raise ValueError('instance_id and agent_id are required')
  if not isinstance(selection,dict) or selection.get('kind')!='RuntimeSelection':raise ValueError('validated runtime selection is required')
  p=normalize_policy(policy);now=utc_timestamp();ph=self.dialect.placeholder;days=json.dumps(p['weekdays'],separators=(',',':'));sel=json.dumps(selection,separators=(',',':'),sort_keys=True)
  with self.session(transaction=True) as s:
   old=s.execute(f'SELECT revision FROM instance_update_policy WHERE instance_id={ph}',(iid,)).fetchone();rev=int(old['revision'] or 0)+1 if old else 1
   if old:s.execute(f'DELETE FROM instance_update_policy WHERE instance_id={ph}',(iid,))
   s.execute('INSERT INTO instance_update_policy(instance_id,mode,timezone,weekdays_json,start_time,duration_minutes,check_interval_seconds,backup_before_update,selection_json,revision,requested_by,created_at,updated_at) '+f'VALUES ({self.dialect.parameters(13)})',(iid,p['mode'],p['timezone'],days,p['start_time'],p['duration_minutes'],p['check_interval_seconds'],1 if p['backup_before_update'] else 0,sel,rev,str(requested_by or '') or None,now,now))
   state=s.execute(f'SELECT instance_id FROM instance_update_state WHERE instance_id={ph}',(iid,)).fetchone()
   provider=str(selection.get('provider') or 'unknown');target=str((selection.get('install') or {}).get('package_id') or selection.get('version') or '')
   if state:s.execute(f'UPDATE instance_update_state SET agent_id={ph},provider={ph},target_key={ph},updated_at={ph} WHERE instance_id={ph}',(aid,provider,target,now,iid))
   else:s.execute('INSERT INTO instance_update_state(instance_id,agent_id,provider,target_key,state,rollback_supported,updated_at) '+f'VALUES ({self.dialect.parameters(7)})',(iid,aid,provider,target,'unknown',0,now))
  return self.snapshot(iid)
 def snapshot(self,instance_id:str)->dict[str,Any]:
  ph=self.dialect.placeholder;iid=str(instance_id)
  with self.session() as s:
   p=s.execute(f'SELECT * FROM instance_update_policy WHERE instance_id={ph}',(iid,)).fetchone();st=s.execute(f'SELECT * FROM instance_update_state WHERE instance_id={ph}',(iid,)).fetchone();runs=s.execute(f'SELECT * FROM instance_update_runs WHERE instance_id={ph} ORDER BY created_at DESC LIMIT 25',(iid,)).fetchall()
  if not p:raise KeyError(iid)
  policy=dict(p);policy['weekdays']=json.loads(policy.pop('weekdays_json'));policy.pop('selection_json',None);state=dict(st) if st else None
  return {'instance_id':iid,'policy':policy,'state':state,'runs':[dict(x) for x in runs]}
 def _row(self,instance_id:str):
  ph=self.dialect.placeholder
  with self.session() as s:return s.execute(f'SELECT p.*,s.agent_id,s.state,s.last_checked_at,s.active_job_id,s.available_version,s.installed_version FROM instance_update_policy p JOIN instance_update_state s ON s.instance_id=p.instance_id WHERE p.instance_id={ph}',(instance_id,)).fetchone()
 def _selection(self,row,operation:str)->dict[str,Any]:
  selection=json.loads(row['selection_json']);selection=dict(selection);selection['_server_update']={'instance_id':str(row['instance_id']),'operation':operation,'backup_before_update':bool(row['backup_before_update'])};return selection
 def queue_check(self,instance_id:str,*,requested_by:str='scheduler')->dict[str,Any]:
  row=self._row(instance_id)
  if not row:raise KeyError(instance_id)
  job=AgentGameDataRepository(self.backend).enqueue(agent_id=str(row['agent_id']),action='verify',environment_id=str(json.loads(row['selection_json']).get('environment_id') or row['instance_id']),selector='current',selection=self._selection(row,'check'),requested_by=requested_by);self._activate(instance_id,job['job_id'],'checking');return job
 def queue_update(self,instance_id:str,*,requested_by:str='scheduler',trigger_type:str='automatic')->dict[str,Any]:
  row=self._row(instance_id)
  if not row:raise KeyError(instance_id)
  run='server-update-'+uuid.uuid4().hex;now=utc_timestamp();job=AgentGameDataRepository(self.backend).enqueue(agent_id=str(row['agent_id']),action='update',environment_id=str(json.loads(row['selection_json']).get('environment_id') or row['instance_id']),selector='current',selection=self._selection(row,'update'),requested_by=requested_by);ph=self.dialect.placeholder
  with self.session(transaction=True) as s:
   s.execute('INSERT INTO instance_update_runs(run_id,instance_id,agent_id,game_data_job_id,trigger_type,installed_before,target_version,status,rollback_supported,created_at,updated_at) '+f'VALUES ({self.dialect.parameters(11)})',(run,str(row['instance_id']),str(row['agent_id']),job['job_id'],trigger_type,row['installed_version'],row['available_version'],'queued',0,now,now))
  self._activate(instance_id,job['job_id'],'updating');return {'run_id':run,'job':job}
 def _activate(self,iid,job,state):
  ph=self.dialect.placeholder
  with self.session(transaction=True) as s:s.execute(f'UPDATE instance_update_state SET active_job_id={ph},state={ph},updated_at={ph} WHERE instance_id={ph}',(job,state,utc_timestamp(),iid))
 def schedule_due_for_agent(self,agent_id:str)->None:
  now=datetime.now(timezone.utc);ph=self.dialect.placeholder
  with self.session() as s:rows=s.execute(f'SELECT p.instance_id,p.check_interval_seconds,s.last_checked_at,s.active_job_id FROM instance_update_policy p JOIN instance_update_state s ON s.instance_id=p.instance_id WHERE s.agent_id={ph}',(agent_id,)).fetchall()
  for row in rows:
   if row['active_job_id']:continue
   last=_parse(row['last_checked_at']);interval=int(row['check_interval_seconds'] or 3600)
   if last is None or (now-last).total_seconds()>=interval:
    try:self.queue_check(str(row['instance_id']))
    except Exception:continue
 def apply_game_data_result(self,job:dict[str,Any],result:dict[str,Any])->None:
  selection=job.get('selection') if isinstance(job.get('selection'),dict) else {};meta=selection.get('_server_update') if isinstance(selection.get('_server_update'),dict) else None
  if not meta:return
  iid=str(meta.get('instance_id') or '');operation=str(meta.get('operation') or '');status=str(result.get('status') or '');now=utc_timestamp();ph=self.dialect.placeholder
  if status=='running':return
  if status=='failed':
   with self.session(transaction=True) as s:s.execute(f'UPDATE instance_update_state SET state={ph},last_error_code={ph},active_job_id=NULL,updated_at={ph} WHERE instance_id={ph}',('update_failed' if operation=='update' else 'unknown','agent_operation_failed',now,iid));s.execute(f'UPDATE instance_update_runs SET status={ph},error_code={ph},completed_at={ph},updated_at={ph} WHERE game_data_job_id={ph}',('failed','agent_operation_failed',now,now,job['job_id']))
   return
  detail=result.get('update_status') if operation=='check' else result.get('update_status_after')
  if not isinstance(detail,dict):detail={}
  state=str(detail.get('state') or ('updated' if operation=='update' else 'unknown'));installed=detail.get('installed_version');available=detail.get('available_version')
  with self.session(transaction=True) as s:
   s.execute(f'UPDATE instance_update_state SET installed_version={ph},available_version={ph},state={ph},rollback_supported={ph},last_checked_at={ph},last_error_code=NULL,active_job_id=NULL,updated_at={ph} WHERE instance_id={ph}',(installed,available,'updated' if operation=='update' else state,1 if detail.get('rollback_supported') else 0,now,now,iid))
   if operation=='update':s.execute(f'UPDATE instance_update_runs SET installed_after={ph},status={ph},completed_at={ph},updated_at={ph} WHERE game_data_job_id={ph}',(installed,'completed',now,now,job['job_id']))
  if operation=='check' and state=='update_available':
   row=self._row(iid);policy={'mode':row['mode'],'timezone':row['timezone'],'weekdays':json.loads(row['weekdays_json']),'start_time':row['start_time'],'duration_minutes':row['duration_minutes'],'check_interval_seconds':row['check_interval_seconds'],'backup_before_update':bool(row['backup_before_update'])}
   if should_apply(policy,state):
    try:self.queue_update(iid,trigger_type=policy['mode'])
    except Exception:pass

__all__=['ServerUpdateRepository']
