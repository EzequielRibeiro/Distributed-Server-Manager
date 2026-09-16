#!/usr/bin/env python3
"""Selection and lease coordination for policy-driven managed-content updates."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from typing import Any,Iterator
from alert_repository import AlertSession,dialect_for_backend
from core.agent_health import utc_timestamp
from core.server_update_platform import effective_content_update_mode,normalize_content_update_mode,normalize_policy,should_apply_content


def _parse_time(value:Any)->datetime|None:
 try:return datetime.fromisoformat(str(value).replace('Z','+00:00'))
 except Exception:return None


class ContentUpdateDispatchRepository:
 def __init__(self,backend):self.backend=backend;self.dialect=dialect_for_backend(backend)
 def initialize(self):return self.backend.initialize()
 @contextmanager
 def session(self,transaction:bool=False)->Iterator[AlertSession]:
  ctx=self.backend.transaction() if transaction else self.backend.connect()
  with ctx as connection:
   session=AlertSession(self.backend,connection)
   try:yield session
   finally:session.close()
 def _policy(self,row:dict[str,Any])->tuple[dict[str,Any],str]:
  override=normalize_content_update_mode(row.get('override_mode') or 'inherit');has_instance_policy=bool(row.get('instance_mode'))
  if has_instance_policy:
   weekdays=json.loads(row.get('instance_weekdays_json') or '[]');policy=normalize_policy({'mode':row.get('instance_mode'),'timezone':row.get('instance_timezone'),'weekdays':weekdays,'start_time':row.get('instance_start_time'),'duration_minutes':row.get('instance_duration_minutes'),'check_interval_seconds':row.get('instance_check_interval_seconds'),'backup_before_update':bool(row.get('instance_backup_before_update'))})
  else:policy=normalize_policy({})
  return policy,effective_content_update_mode(policy,override)
 def _eligible(self,row:dict[str,Any],now:datetime)->tuple[bool,str]:
  override=normalize_content_update_mode(row.get('override_mode') or 'inherit')
  if override=='maintenance' and not row.get('instance_mode'):return False,'maintenance_without_instance_policy'
  try:policy,effective=self._policy(row)
  except Exception:return False,'invalid'
  return should_apply_content(policy,'update_available',override=override,now=now),effective
 def _coalesced(self,row:dict[str,Any],effective_mode:str)->bool:
  return effective_mode=='maintenance' and bool(row.get('maintenance_enabled')) and bool(row.get('maintenance_coalesce_updates'))
 def _rows(self,*,limit:int=1000,instance_id:str|None=None)->list[dict[str,Any]]:
  count=max(1,min(int(limit),2000));ph=self.dialect.placeholder;where="u.state='update_available' AND a.desired_state='installed'";params:list[Any]=[]
  if instance_id is not None:where+=f' AND u.instance_id={ph}';params.append(str(instance_id))
  sql=("SELECT u.agent_id,u.instance_id,u.content_id,u.provider,u.content_type,u.installed_version,u.available_version,u.dispatched_available_version,u.dispatched_assignment_revision,"+
       "u.dispatch_attempted_at,u.dispatch_attempted_version,u.dispatch_attempted_assignment_revision,u.dispatch_error,a.revision AS assignment_revision,a.checksum AS assignment_checksum,a.desired_state,"+
       "p.mode AS override_mode,ip.mode AS instance_mode,ip.timezone AS instance_timezone,ip.weekdays_json AS instance_weekdays_json,ip.start_time AS instance_start_time,"+
       "ip.duration_minutes AS instance_duration_minutes,ip.check_interval_seconds AS instance_check_interval_seconds,ip.backup_before_update AS instance_backup_before_update,"+
       "mp.enabled AS maintenance_enabled,mp.coalesce_updates AS maintenance_coalesce_updates " +
       "FROM content_update_state u JOIN content_assignments a ON a.instance_id=u.instance_id AND a.content_id=u.content_id AND a.agent_id=u.agent_id AND a.provider=u.provider " +
       "LEFT JOIN content_update_policy p ON p.instance_id=u.instance_id AND p.content_id=u.content_id " +
       "LEFT JOIN instance_update_policy ip ON ip.instance_id=u.instance_id " +
       "LEFT JOIN instance_maintenance_policy mp ON mp.instance_id=u.instance_id " +
       f"WHERE {where} ORDER BY u.instance_id,u.content_id LIMIT {count}")
  with self.session() as session:return [dict(row) for row in session.execute(sql,tuple(params)).fetchall()]
 def _undispatched(self,row:dict[str,Any])->bool:
  available=str(row.get('available_version') or '').strip();revision=int(row.get('assignment_revision') or 0)
  if not available or revision<1:return False
  return not (str(row.get('dispatched_available_version') or '')==available and int(row.get('dispatched_assignment_revision') or 0)==revision)
 def due(self,*,limit:int=200,now:datetime|None=None,retry_seconds:int=300)->list[dict[str,Any]]:
  current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc);result=[]
  for row in self._rows(limit=max(limit,500)):
   if not self._undispatched(row):continue
   attempted=_parse_time(row.get('dispatch_attempted_at'));same_attempt=str(row.get('dispatch_attempted_version') or '')==str(row.get('available_version') or '') and int(row.get('dispatch_attempted_assignment_revision') or 0)==int(row.get('assignment_revision') or 0)
   if same_attempt and attempted is not None and (current-attempted.astimezone(timezone.utc)).total_seconds()<max(30,int(retry_seconds)):continue
   allowed,mode=self._eligible(row,current)
   if not allowed or self._coalesced(row,mode):continue
   row['effective_mode']=mode;result.append(row)
   if len(result)>=max(1,min(int(limit),1000)):break
  return result
 def due_for_maintenance(self,instance_id:str,*,limit:int=200)->list[dict[str,Any]]:
  result=[]
  for row in self._rows(limit=max(limit,500),instance_id=str(instance_id)):
   if not self._undispatched(row):continue
   override=normalize_content_update_mode(row.get('override_mode') or 'inherit')
   if override=='maintenance' and not row.get('instance_mode'):continue
   try:_,mode=self._policy(row)
   except Exception:continue
   if not self._coalesced(row,mode):continue
   row['effective_mode']=mode;result.append(row)
   if len(result)>=max(1,min(int(limit),1000)):break
  return result
 def claim(self,item:dict[str,Any])->bool:
  aid=str(item.get('agent_id') or '');iid=str(item.get('instance_id') or '');cid=str(item.get('content_id') or '');available=str(item.get('available_version') or '');provider=str(item.get('provider') or '');revision=int(item.get('assignment_revision') or 0);old_attempt=item.get('dispatch_attempted_at');ph=self.dialect.placeholder;now=utc_timestamp()
  if not aid or not iid or not cid or not available or not provider or revision<1:return False
  with self.session(transaction=True) as session:
   current=session.execute(f'SELECT revision,desired_state,agent_id,provider FROM content_assignments WHERE instance_id={ph} AND content_id={ph}',(iid,cid)).fetchone()
   if not current or str(current['agent_id'] or '')!=aid or str(current['provider'] or '')!=provider or str(current['desired_state'] or '')!='installed' or int(current['revision'] or 0)!=revision:return False
   if old_attempt is None:
    sql=f"UPDATE content_update_state SET dispatch_attempted_at={ph},dispatch_attempted_version={ph},dispatch_attempted_assignment_revision={ph},dispatch_error=NULL,updated_at={ph} WHERE agent_id={ph} AND instance_id={ph} AND content_id={ph} AND state='update_available' AND provider={ph} AND available_version={ph} AND dispatch_attempted_at IS NULL"
    cursor=session.execute(sql,(now,available,revision,now,aid,iid,cid,provider,available))
   else:
    sql=f"UPDATE content_update_state SET dispatch_attempted_at={ph},dispatch_attempted_version={ph},dispatch_attempted_assignment_revision={ph},dispatch_error=NULL,updated_at={ph} WHERE agent_id={ph} AND instance_id={ph} AND content_id={ph} AND state='update_available' AND provider={ph} AND available_version={ph} AND dispatch_attempted_at={ph}"
    cursor=session.execute(sql,(now,available,revision,now,aid,iid,cid,provider,available,old_attempt))
   return int(getattr(cursor,'rowcount',0) or 0)==1
 def complete(self,item:dict[str,Any],assignment_revision:int)->None:
  ph=self.dialect.placeholder;now=utc_timestamp();aid=str(item.get('agent_id') or '');iid=str(item.get('instance_id') or '');cid=str(item.get('content_id') or '');available=str(item.get('available_version') or '')
  with self.session(transaction=True) as session:session.execute(f'UPDATE content_update_state SET dispatched_available_version={ph},dispatched_assignment_revision={ph},dispatch_error=NULL,updated_at={ph} WHERE agent_id={ph} AND instance_id={ph} AND content_id={ph}',(available,int(assignment_revision),now,aid,iid,cid))
 def fail(self,item:dict[str,Any],error:Any)->None:
  ph=self.dialect.placeholder;now=utc_timestamp();message=str(error or 'content update dispatch failed').replace('\x00','')[:2000]
  with self.session(transaction=True) as session:session.execute(f'UPDATE content_update_state SET dispatch_error={ph},updated_at={ph} WHERE agent_id={ph} AND instance_id={ph} AND content_id={ph}',(message,now,str(item.get('agent_id') or ''),str(item.get('instance_id') or ''),str(item.get('content_id') or '')))
 def alignment(self,instance_id:str,expected:dict[str,int])->dict[str,Any]:
  iid=str(instance_id);ph=self.dialect.placeholder;pending=[];failed=[];aligned=[]
  if not expected:return {'ready':True,'pending':pending,'failed':failed,'aligned':aligned}
  with self.session() as session:
   for cid,wanted in sorted(expected.items()):
    row=session.execute('SELECT a.revision,a.checksum,s.applied_revision,s.applied_checksum,s.status,s.last_error FROM content_assignments a LEFT JOIN agent_content_state s ON s.instance_id=a.instance_id AND s.content_id=a.content_id AND s.agent_id=a.agent_id '+f'WHERE a.instance_id={ph} AND a.content_id={ph}',(iid,str(cid))).fetchone()
    if not row:failed.append({'content_id':cid,'error':'content_assignment_missing'});continue
    current=int(row['revision'] or 0);status=str(row['status'] or 'pending')
    if current!=int(wanted):failed.append({'content_id':cid,'error':'content_revision_changed','expected_revision':int(wanted),'current_revision':current});continue
    if status in {'failed','rollback_failed','security_blocked','security_scan_failed'}:failed.append({'content_id':cid,'error':str(row['last_error'] or status)[:500]});continue
    if status=='applied' and int(row['applied_revision'] or 0)==current and str(row['applied_checksum'] or '')==str(row['checksum'] or ''):aligned.append(cid)
    else:pending.append(cid)
  return {'ready':not pending and not failed,'pending':pending,'failed':failed,'aligned':aligned}


__all__=['ContentUpdateDispatchRepository']
