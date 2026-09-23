#!/usr/bin/env python3
"""Persistent M5 maintenance policies, schedules and run state."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import json,uuid
from typing import Any,Iterator
from alert_repository import AlertSession,dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp
from core.maintenance_platform import next_due_at,normalize_policy

def _parse(value:Any)->datetime|None:
 if value in {None,""}:return None
 try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)
 except (TypeError,ValueError):return None
def _stamp(value:datetime|None)->str|None:return value.astimezone(timezone.utc).isoformat().replace("+00:00","Z") if value else None

class MaintenanceRepository:
 def __init__(self,backend:DatabaseBackend):self.backend=backend;self.dialect=dialect_for_backend(backend)
 def initialize(self):return self.backend.initialize()
 @contextmanager
 def session(self,transaction:bool=False)->Iterator[AlertSession]:
  ctx=self.backend.transaction() if transaction else self.backend.connect()
  with ctx as connection:
   session=AlertSession(self.backend,connection)
   try:yield session
   finally:session.close()
 def _decode_policy(self,row:dict[str,Any])->dict[str,Any]:
  value=dict(row);value['weekdays']=json.loads(value.pop('weekdays_json') or '[]');value['warning_offsets_seconds']=json.loads(value.pop('warning_offsets_json') or '[]');value['enabled']=bool(value.get('enabled'));value['broadcast_enabled']=bool(value.get('broadcast_enabled'));value['coalesce_updates']=bool(value.get('coalesce_updates'));return value
 def set_policy(self,instance_id:str,raw:dict[str,Any]|None,*,requested_by:str|None=None,now:datetime|None=None)->dict[str,Any]:
  iid=str(instance_id or '').strip()
  if not iid or len(iid)>191:raise ValueError('valid instance_id is required')
  policy=normalize_policy(raw);current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc);stamp=_stamp(current);ph=self.dialect.placeholder
  with self.session(transaction=True) as session:
   instance=session.execute(f'SELECT agent_id FROM instances WHERE id={ph}',(iid,)).fetchone()
   if not instance:raise KeyError(iid)
   if not str(instance['agent_id'] or '').strip():raise ValueError('instance has no canonical Agent binding')
   old=session.execute(f'SELECT revision,created_at FROM instance_maintenance_policy WHERE instance_id={ph}',(iid,)).fetchone();state=session.execute(f'SELECT * FROM instance_maintenance_state WHERE instance_id={ph}',(iid,)).fetchone()
   if state and state['active_run_id']:raise RuntimeError('maintenance policy cannot change while a run is active')
   revision=int(old['revision'] or 0)+1 if old else 1;created=old['created_at'] if old else stamp;anchor=(state['last_completed_at'] if state else None) or stamp;due=next_due_at(policy,now=current,anchor=anchor)
   if old:session.execute(f'DELETE FROM instance_maintenance_policy WHERE instance_id={ph}',(iid,))
   session.execute('INSERT INTO instance_maintenance_policy(instance_id,enabled,schedule_mode,timezone,weekdays_json,start_time,interval_seconds,warning_offsets_json,warning_template,broadcast_enabled,coalesce_updates,revision,requested_by,created_at,updated_at) '+f'VALUES ({self.dialect.parameters(15)})',(iid,1 if policy['enabled'] else 0,policy['schedule_mode'],policy['timezone'],json.dumps(policy['weekdays'],separators=(',',':')),policy['start_time'],policy['interval_seconds'],json.dumps(policy['warning_offsets_seconds'],separators=(',',':')),policy['warning_template'],1 if policy['broadcast_enabled'] else 0,1 if policy['coalesce_updates'] else 0,revision,str(requested_by or '') or None,created,stamp))
   if state:session.execute(f'UPDATE instance_maintenance_state SET next_due_at={ph},last_error=NULL,updated_at={ph} WHERE instance_id={ph}',(_stamp(due),stamp,iid))
   else:session.execute('INSERT INTO instance_maintenance_state(instance_id,next_due_at,active_run_id,last_started_at,last_completed_at,last_error,updated_at) '+f'VALUES ({self.dialect.parameters(7)})',(iid,_stamp(due),None,None,None,None,stamp))
  return self.snapshot(iid)
 def snapshot(self,instance_id:str)->dict[str,Any]:
  iid=str(instance_id);ph=self.dialect.placeholder
  with self.session() as session:
   policy=session.execute(f'SELECT * FROM instance_maintenance_policy WHERE instance_id={ph}',(iid,)).fetchone();state=session.execute(f'SELECT * FROM instance_maintenance_state WHERE instance_id={ph}',(iid,)).fetchone();runs=session.execute(f'SELECT run_id FROM instance_maintenance_runs WHERE instance_id={ph} ORDER BY created_at DESC LIMIT 25',(iid,)).fetchall()
  if not policy:raise KeyError(iid)
  return {'instance_id':iid,'policy':self._decode_policy(dict(policy)),'state':dict(state) if state else None,'runs':[self.run(str(row['run_id'])) for row in runs]}
 def instance_context(self,instance_id:str)->dict[str,Any]:
  ph=self.dialect.placeholder
  with self.session() as session:row=session.execute(f'SELECT id,agent_id,game_id,runtime_id,status FROM instances WHERE id={ph}',(str(instance_id),)).fetchone()
  if not row:raise KeyError(instance_id)
  return dict(row)
 def run(self,run_id:str)->dict[str,Any]:
  ph=self.dialect.placeholder
  with self.session() as session:row=session.execute(f'SELECT * FROM instance_maintenance_runs WHERE run_id={ph}',(str(run_id),)).fetchone()
  if not row:raise KeyError(run_id)
  value=dict(row)
  for source,target,default in (('event_json','event',{}),('warnings_sent_json','warnings_sent',[]),('broadcast_ids_json','broadcast_ids',{})):
   raw=value.pop(source,None)
   try:value[target]=json.loads(raw) if raw else default
   except (TypeError,ValueError):value[target]=default
  return value
 def _policy_state_rows(self)->list[dict[str,Any]]:
  with self.session() as session:rows=session.execute('SELECT p.*,s.next_due_at,s.active_run_id,i.agent_id FROM instance_maintenance_policy p JOIN instance_maintenance_state s ON s.instance_id=p.instance_id JOIN instances i ON i.id=p.instance_id WHERE p.enabled=1 ORDER BY s.next_due_at,p.instance_id').fetchall()
  return [dict(row) for row in rows]
 def candidates(self,*,now:datetime|None=None,limit:int=500)->list[str]:
  current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc);result=[]
  for row in self._policy_state_rows():
   if row.get('active_run_id'):continue
   due=_parse(row.get('next_due_at'))
   if due is None:continue
   policy=self._decode_policy(row);horizon=max(policy['warning_offsets_seconds'],default=0) if policy['broadcast_enabled'] else 0
   if current>=due-timedelta(seconds=horizon):result.append(str(row['instance_id']))
   if len(result)>=max(1,min(int(limit),1000)):break
  return result
 def ensure_run(self,instance_id:str,*,now:datetime|None=None)->dict[str,Any]|None:
  iid=str(instance_id);current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc);ph=self.dialect.placeholder;selected=None
  with self.session(transaction=True) as session:
   state=session.execute(f'SELECT next_due_at,active_run_id FROM instance_maintenance_state WHERE instance_id={ph}',(iid,)).fetchone();policy_row=session.execute(f'SELECT * FROM instance_maintenance_policy WHERE instance_id={ph}',(iid,)).fetchone();instance=session.execute(f'SELECT agent_id FROM instances WHERE id={ph}',(iid,)).fetchone()
   if not state or not policy_row or not instance or not bool(policy_row['enabled']):return None
   if state['active_run_id']:selected=str(state['active_run_id'])
   else:
    due=_parse(state['next_due_at']);policy=self._decode_policy(dict(policy_row));horizon=max(policy['warning_offsets_seconds'],default=0) if policy['broadcast_enabled'] else 0
    if due is None or current<due-timedelta(seconds=horizon):return None
    selected='maintenance-'+uuid.uuid4().hex;stamp=_stamp(current)
    session.execute('INSERT INTO instance_maintenance_runs(run_id,instance_id,agent_id,trigger_type,due_at,status,stage,event_json,warnings_sent_json,broadcast_ids_json,preflight_command_id,save_command_id,stop_command_id,start_command_id,lifecycle_command_id,readiness_command_id,error_code,error_detail,created_at,started_at,completed_at,updated_at) '+f'VALUES ({self.dialect.parameters(22)})',(selected,iid,str(instance['agent_id']),'scheduled',_stamp(due),'pending','planning','{}','[]','{}',None,None,None,None,None,None,None,None,stamp,None,None,stamp));session.execute(f'UPDATE instance_maintenance_state SET active_run_id={ph},last_error=NULL,updated_at={ph} WHERE instance_id={ph}',(selected,stamp,iid))
  return self.run(selected) if selected else None
 def active_runs(self,limit:int=500)->list[dict[str,Any]]:
  with self.session() as session:rows=session.execute(f"SELECT run_id FROM instance_maintenance_runs WHERE status IN ('pending','running') ORDER BY due_at,created_at LIMIT {max(1,min(int(limit),1000))}").fetchall()
  return [self.run(str(row['run_id'])) for row in rows]
 def policy(self,instance_id:str)->dict[str,Any]:return self.snapshot(instance_id)['policy']
 def set_event(self,run_id:str,event:dict[str,Any])->dict[str,Any]:
  if not isinstance(event,dict) or event.get('kind')!='CapivaraMaintenanceEvent':raise ValueError('valid maintenance event is required')
  ph=self.dialect.placeholder;stamp=utc_timestamp();payload=json.dumps(event,separators=(',',':'),sort_keys=True)
  with self.session(transaction=True) as session:session.execute(f"UPDATE instance_maintenance_runs SET event_json={ph},stage=CASE WHEN stage='planning' THEN 'warning' ELSE stage END,updated_at={ph} WHERE run_id={ph} AND (event_json='{{}}' OR event_json IS NULL)",(payload,stamp,run_id))
  return self.run(run_id)
 def update_event(self,run_id:str,event:dict[str,Any],*,stage:str|None=None)->dict[str,Any]:
  if not isinstance(event,dict) or event.get('kind')!='CapivaraMaintenanceEvent':raise ValueError('valid maintenance event is required')
  ph=self.dialect.placeholder;stamp=utc_timestamp();payload=json.dumps(event,separators=(',',':'),sort_keys=True)
  with self.session(transaction=True) as session:
   if stage is None:session.execute(f'UPDATE instance_maintenance_runs SET event_json={ph},updated_at={ph} WHERE run_id={ph} AND status IN (\'pending\',\'running\')',(payload,stamp,run_id))
   else:session.execute(f'UPDATE instance_maintenance_runs SET event_json={ph},stage={ph},updated_at={ph} WHERE run_id={ph} AND status IN (\'pending\',\'running\')',(payload,str(stage)[:32],stamp,run_id))
  return self.run(run_id)
 def record_warning(self,run_id:str,offset:int,broadcast_id:str)->dict[str,Any]:
  run=self.run(run_id);sent={int(v) for v in run['warnings_sent']};sent.add(int(offset));broadcasts=dict(run['broadcast_ids']);broadcasts[str(int(offset))]=str(broadcast_id);ph=self.dialect.placeholder;stamp=utc_timestamp()
  with self.session(transaction=True) as session:session.execute(f'UPDATE instance_maintenance_runs SET warnings_sent_json={ph},broadcast_ids_json={ph},updated_at={ph} WHERE run_id={ph}',(json.dumps(sorted(sent,reverse=True),separators=(',',':')),json.dumps(broadcasts,separators=(',',':'),sort_keys=True),stamp,run_id))
  return self.run(run_id)
 def _mark_command(self,run_id:str,column:str,command_id:str,stage:str,*,started:bool=False)->dict[str,Any]:
  allowed={'preflight_command_id','save_command_id','stop_command_id','start_command_id','readiness_command_id','lifecycle_command_id'}
  if column not in allowed:raise ValueError('invalid maintenance command column')
  ph=self.dialect.placeholder;stamp=utc_timestamp();started_sql=f",started_at=COALESCE(started_at,{ph})" if started else '';params=[command_id,stage]
  if started:params.append(stamp)
  params.extend([stamp,run_id]);sql=f"UPDATE instance_maintenance_runs SET {column}={ph},status='running',stage={ph}{started_sql},updated_at={ph} WHERE run_id={ph} AND {column} IS NULL"
  with self.session(transaction=True) as session:session.execute(sql,tuple(params))
  return self.run(run_id)
 def mark_preflight(self,run_id:str,command_id:str)->dict[str,Any]:return self._mark_command(run_id,'preflight_command_id',command_id,'preflight')
 def mark_save(self,run_id:str,command_id:str)->dict[str,Any]:return self._mark_command(run_id,'save_command_id',command_id,'saving',started=True)
 def mark_stop(self,run_id:str,command_id:str)->dict[str,Any]:return self._mark_command(run_id,'stop_command_id',command_id,'stopping',started=True)
 def mark_start(self,run_id:str,command_id:str)->dict[str,Any]:return self._mark_command(run_id,'start_command_id',command_id,'starting',started=True)
 def mark_restart(self,run_id:str,command_id:str)->dict[str,Any]:return self._mark_command(run_id,'lifecycle_command_id',command_id,'restarting',started=True)
 def mark_readiness(self,run_id:str,command_id:str)->dict[str,Any]:return self._mark_command(run_id,'readiness_command_id',command_id,'validating')
 def next_due_for_run(self,run_id:str,*,now:datetime|None=None)->datetime|None:
  run=self.run(run_id);policy=self.policy(str(run['instance_id']));current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
  return next_due_at(policy,now=current,anchor=current)
 def finish(self,run_id:str,*,success:bool,error_code:str|None=None,error_detail:str|None=None,now:datetime|None=None,next_due_override:datetime|str|None=None)->dict[str,Any]:
  run=self.run(run_id);policy=self.policy(str(run['instance_id']));current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc);due=_parse(next_due_override) if next_due_override is not None else next_due_at(policy,now=current,anchor=current);stamp=_stamp(current);status='completed' if success else 'failed';stage='completed' if success else 'failed';detail=str(error_detail or '')[:2000] or None;code=str(error_code or '')[:128] or None;ph=self.dialect.placeholder
  with self.session(transaction=True) as session:
   session.execute(f'UPDATE instance_maintenance_runs SET status={ph},stage={ph},error_code={ph},error_detail={ph},completed_at={ph},updated_at={ph} WHERE run_id={ph}',(status,stage,code,detail,stamp,stamp,run_id));session.execute(f'UPDATE instance_maintenance_state SET next_due_at={ph},active_run_id=NULL,last_completed_at={ph},last_error={ph},updated_at={ph} WHERE instance_id={ph}',(_stamp(due),stamp,None if success else detail,stamp,run['instance_id']))
  return self.run(run_id)
__all__=['MaintenanceRepository']
