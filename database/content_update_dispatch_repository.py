#!/usr/bin/env python3
"""Selection and lease coordination for policy-driven managed-content updates."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from typing import Any,Iterator
from alert_repository import AlertSession,dialect_for_backend
from core.agent_health import utc_timestamp
from core.server_update_platform import normalize_content_update_mode,normalize_policy,should_apply_content


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
 def _eligible(self,row:dict[str,Any],now:datetime)->tuple[bool,str]:
  override=normalize_content_update_mode(row.get('override_mode') or 'inherit')
  has_instance_policy=bool(row.get('instance_mode'))
  if override=='maintenance' and not has_instance_policy:return False,'maintenance_without_instance_policy'
  if has_instance_policy:
   try:weekdays=json.loads(row.get('instance_weekdays_json') or '[]')
   except Exception:return False,'invalid_instance_policy'
   try:
    policy=normalize_policy({'mode':row.get('instance_mode'),'timezone':row.get('instance_timezone'),'weekdays':weekdays,'start_time':row.get('instance_start_time'),'duration_minutes':row.get('instance_duration_minutes'),'check_interval_seconds':row.get('instance_check_interval_seconds'),'backup_before_update':bool(row.get('instance_backup_before_update'))})
   except Exception:return False,'invalid_instance_policy'
  else:policy=normalize_policy({})
  return should_apply_content(policy,'update_available',override=override,now=now),override
 def due(self,*,limit:int=200,now:datetime|None=None,retry_seconds:int=300)->list[dict[str,Any]]:
  count=max(1,min(int(limit),1000));current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
  sql=("SELECT u.agent_id,u.instance_id,u.content_id,u.provider,u.content_type,u.installed_version,u.available_version,u.dispatched_available_version,u.dispatched_assignment_revision,"+
       "u.dispatch_attempted_at,u.dispatch_attempted_version,u.dispatch_attempted_assignment_revision,u.dispatch_error,a.revision AS assignment_revision,a.desired_state,"+
       "p.mode AS override_mode,ip.mode AS instance_mode,ip.timezone AS instance_timezone,ip.weekdays_json AS instance_weekdays_json,ip.start_time AS instance_start_time,"+
       "ip.duration_minutes AS instance_duration_minutes,ip.check_interval_seconds AS instance_check_interval_seconds,ip.backup_before_update AS instance_backup_before_update " +
       "FROM content_update_state u JOIN content_assignments a ON a.instance_id=u.instance_id AND a.content_id=u.content_id AND a.agent_id=u.agent_id AND a.provider=u.provider " +
       "LEFT JOIN content_update_policy p ON p.instance_id=u.instance_id AND p.content_id=u.content_id " +
       "LEFT JOIN instance_update_policy ip ON ip.instance_id=u.instance_id " +
       f"WHERE u.state='update_available' AND a.desired_state='installed' ORDER BY u.instance_id,u.content_id LIMIT {count}")
  with self.session() as session:rows=[dict(row) for row in session.execute(sql).fetchall()]
  result=[]
  for row in rows:
   available=str(row.get('available_version') or '').strip();revision=int(row.get('assignment_revision') or 0)
   if not available or revision<1:continue
   if str(row.get('dispatched_available_version') or '')==available and int(row.get('dispatched_assignment_revision') or 0)==revision:continue
   attempted=_parse_time(row.get('dispatch_attempted_at'))
   same_attempt=str(row.get('dispatch_attempted_version') or '')==available and int(row.get('dispatch_attempted_assignment_revision') or 0)==revision
   if same_attempt and attempted is not None and (current-attempted.astimezone(timezone.utc)).total_seconds()<max(30,int(retry_seconds)):continue
   allowed,mode=self._eligible(row,current)
   if not allowed:continue
   row['effective_mode']=mode;result.append(row)
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


__all__=['ContentUpdateDispatchRepository']
