#!/usr/bin/env python3
"""M5 bridge from scheduled maintenance to M4 shared game-server updates."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
import json,uuid
from typing import Any,Iterator
from agent_game_data_repository import AgentGameDataRepository
from alert_repository import AlertSession,dialect_for_backend
from core.agent_health import utc_timestamp
from core.server_update_platform import normalize_policy,should_apply

class MaintenanceGameUpdateCoordinator:
 def __init__(self,backend):self.backend=backend;self.dialect=dialect_for_backend(backend);self.jobs=AgentGameDataRepository(backend);self.jobs.initialize()
 @contextmanager
 def session(self,transaction:bool=False)->Iterator[AlertSession]:
  context=self.backend.transaction() if transaction else self.backend.connect()
  with context as connection:
   session=AlertSession(self.backend,connection)
   try:yield session
   finally:session.close()
 def _row(self,instance_id:str)->dict[str,Any]|None:
  ph=self.dialect.placeholder;sql=("SELECT p.instance_id,p.mode,p.timezone,p.weekdays_json,p.start_time,p.duration_minutes,p.check_interval_seconds,p.backup_before_update,p.selection_json,"+"s.agent_id,s.installed_version,s.available_version,s.state,s.active_job_id FROM instance_update_policy p JOIN instance_update_state s ON s.instance_id=p.instance_id "+f"WHERE p.instance_id={ph}")
  with self.session() as session:row=session.execute(sql,(str(instance_id),)).fetchone()
  return dict(row) if row else None
 def _policy(self,row:dict[str,Any])->dict[str,Any]:
  try:weekdays=json.loads(row.get('weekdays_json') or '[]')
  except Exception:weekdays=[]
  return normalize_policy({'mode':row.get('mode'),'timezone':row.get('timezone'),'weekdays':weekdays,'start_time':row.get('start_time'),'duration_minutes':row.get('duration_minutes'),'check_interval_seconds':row.get('check_interval_seconds'),'backup_before_update':bool(row.get('backup_before_update'))})
 def discover(self,instance_id:str,*,now:datetime|None=None)->list[dict[str,Any]]:
  row=self._row(instance_id)
  if not row or str(row.get('state') or '')!='update_available' or row.get('active_job_id'):return []
  policy=self._policy(row);current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
  if policy['mode']!='maintenance' or not should_apply(policy,'update_available',now=current):return []
  available=str(row.get('available_version') or '').strip()
  return [{'kind':'game-update','ref':'server','available_version':available,'status':'pending'}] if available else []
 def _selection(self,row:dict[str,Any],*,transaction_id:str|None=None)->dict[str,Any]:
  try:selection=json.loads(row.get('selection_json') or '{}')
  except Exception as exc:raise RuntimeError('canonical server update selection is invalid') from exc
  if not isinstance(selection,dict) or selection.get('kind')!='RuntimeSelection':raise RuntimeError('canonical server update selection is unavailable')
  selection=dict(selection);meta={'instance_id':str(row['instance_id']),'backup_before_update':bool(row.get('backup_before_update'))}
  if transaction_id:meta['transaction_id']=str(transaction_id)
  selection['_maintenance_game_update']=dict(meta)
  selection['_server_update']={'instance_id':str(row['instance_id']),'operation':'maintenance','backup_before_update':bool(row.get('backup_before_update')),**({'transaction_id':str(transaction_id)} if transaction_id else {})}
  return selection
 def _claim(self,row:dict[str,Any])->str|None:
  ph=self.dialect.placeholder;lease='maintenance-lease-'+uuid.uuid4().hex;now=utc_timestamp()
  with self.session(transaction=True) as session:cursor=session.execute(f"UPDATE instance_update_state SET active_job_id={ph},state={ph},updated_at={ph} WHERE instance_id={ph} AND state='update_available' AND active_job_id IS NULL AND available_version={ph}",(lease,'updating',now,str(row['instance_id']),str(row.get('available_version') or '')))
  return lease if int(getattr(cursor,'rowcount',0) or 0)==1 else None
 def _replace_lease(self,instance_id:str,lease:str,job_id:str)->None:
  ph=self.dialect.placeholder
  with self.session(transaction=True) as session:
   cursor=session.execute(f'UPDATE instance_update_state SET active_job_id={ph},updated_at={ph} WHERE instance_id={ph} AND active_job_id={ph}',(job_id,utc_timestamp(),instance_id,lease))
   if int(getattr(cursor,'rowcount',0) or 0)!=1:raise RuntimeError('server update maintenance lease was lost')
 def _release(self,instance_id:str,*,state:str,error:str|None=None)->None:
  ph=self.dialect.placeholder
  with self.session(transaction=True) as session:session.execute(f'UPDATE instance_update_state SET state={ph},active_job_id=NULL,last_error_code={ph},updated_at={ph} WHERE instance_id={ph}',(state,str(error or '')[:128] or None,utc_timestamp(),instance_id))
 def _queue(self,row:dict[str,Any],action:str,*,transaction_id:str|None=None)->dict[str,Any]:
  selection=self._selection(row,transaction_id=transaction_id);environment=str(selection.get('environment_id') or row['instance_id']);return self.jobs.enqueue(agent_id=str(row['agent_id']),action=action,environment_id=environment,selector='current',selection=selection,requested_by='maintenance-worker')
 @staticmethod
 def _maintenance_result(job:dict[str,Any])->dict[str,Any]:
  result=job.get('result') if isinstance(job.get('result'),dict) else {};detail=result.get('maintenance_update') if isinstance(result.get('maintenance_update'),dict) else {};return dict(detail)
 def prepare(self,instance_id:str,item:dict[str,Any])->tuple[dict[str,Any],bool]:
  value=dict(item);row=self._row(instance_id)
  if not row:value.update(status='failed',error='server update policy is unavailable');return value,True
  job_id=str(value.get('job_id') or '').strip()
  if not job_id:
   lease=self._claim(row)
   if lease is None:return value,False
   try:job=self._queue(row,'maintenance-update');self._replace_lease(str(instance_id),lease,str(job['job_id']))
   except Exception:self._release(str(instance_id),state='update_available',error='maintenance_enqueue_failed');raise
   value.update(status='dispatched',job_id=str(job['job_id']));return value,False
  job=self.jobs.snapshot(job_id);status=str(job.get('status') or '')
  if status in {'queued','delivered','running'}:return value,False
  if status!='completed':self._release(str(instance_id),state='update_available',error='maintenance_update_failed');value.update(status='failed',error=str(job.get('last_error') or 'game update failed')[:500]);return value,True
  detail=self._maintenance_result(job)
  if not detail.get('changed'):self._release(str(instance_id),state='up_to_date');value.update(status='aligned');return value,True
  transaction_id=str(detail.get('transaction_id') or '').strip()
  if not transaction_id:self._release(str(instance_id),state='update_available',error='missing_transaction_id');value.update(status='failed',error='Agent did not return maintenance transaction id');return value,True
  value.update(status='activated',transaction_id=transaction_id);return value,True
 def finalize(self,instance_id:str,item:dict[str,Any])->tuple[dict[str,Any],bool]:
  value=dict(item)
  if value.get('status') in {'aligned','committed'}:return value,True
  transaction_id=str(value.get('transaction_id') or '').strip()
  if not transaction_id:return value,True
  row=self._row(instance_id)
  if not row:value.update(status='failed',error='server update policy disappeared before commit');return value,True
  job_id=str(value.get('finalize_job_id') or '').strip()
  if not job_id:job=self._queue(row,'maintenance-commit',transaction_id=transaction_id);value['finalize_job_id']=str(job['job_id']);return value,False
  job=self.jobs.snapshot(job_id);status=str(job.get('status') or '')
  if status in {'queued','delivered','running'}:return value,False
  if status!='completed':value.update(status='failed',error=str(job.get('last_error') or 'game update commit failed')[:500]);return value,True
  available=str(row.get('available_version') or value.get('available_version') or '').strip();ph=self.dialect.placeholder;now=utc_timestamp()
  with self.session(transaction=True) as session:session.execute(f"UPDATE instance_update_state SET installed_version={ph},state='updated',active_job_id=NULL,last_error_code=NULL,last_checked_at={ph},updated_at={ph} WHERE instance_id={ph}",(available,now,now,str(instance_id)))
  value['status']='committed';return value,True
 def rollback(self,instance_id:str,item:dict[str,Any])->tuple[dict[str,Any],bool]:
  value=dict(item);transaction_id=str(value.get('transaction_id') or '').strip()
  if not transaction_id or value.get('status')=='rolled_back':return value,True
  row=self._row(instance_id)
  if not row:value.update(status='failed',error='server update policy disappeared before rollback');return value,True
  job_id=str(value.get('rollback_job_id') or '').strip()
  if not job_id:job=self._queue(row,'maintenance-rollback',transaction_id=transaction_id);value.update(status='rolling_back',rollback_job_id=str(job['job_id']));return value,False
  job=self.jobs.snapshot(job_id);status=str(job.get('status') or '')
  if status in {'queued','delivered','running'}:return value,False
  if status!='completed':value.update(status='failed',error=str(job.get('last_error') or 'game update rollback failed')[:500]);return value,True
  self._release(str(instance_id),state='update_available',error='maintenance_readiness_rollback');value['status']='rolled_back';return value,True

__all__=['MaintenanceGameUpdateCoordinator']
