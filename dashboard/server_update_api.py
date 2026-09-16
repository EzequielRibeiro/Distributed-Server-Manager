#!/usr/bin/env python3
"""Controller API for universal server/content update policy and operations."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from alert_repository import AlertSession,dialect_for_backend
from agent_game_data_api import prepare_runtime_selection,_require_runtime_prerequisites
from core.server_update_platform import normalize_policy
from server_update_repository import ServerUpdateRepository

_PUBLIC_POLICY_FIELDS=("mode","timezone","weekdays","start_time","duration_minutes","check_interval_seconds","backup_before_update")

def _require_admin(user:dict[str,Any]|None)->str:
 if not user or str(user.get('role') or '').lower()!='admin':raise PermissionError('administrator access required')
 return str(user.get('username') or user.get('id') or 'admin')

def _instance(backend,instance_id:str)->dict[str,Any]:
 iid=str(instance_id or '').strip()
 if not iid or len(iid)>191:raise ValueError('valid instance_id is required')
 dialect=dialect_for_backend(backend)
 with backend.connect() as c:
  s=AlertSession(backend,c)
  try:row=s.execute(f'SELECT id,agent_id,runtime_id,game_id,status FROM instances WHERE id={dialect.placeholder}',(iid,)).fetchone()
  finally:s.close()
 if not row:raise KeyError(iid)
 value=dict(row)
 if not value.get('agent_id') or not value.get('runtime_id'):raise ValueError('instance has no canonical Agent/runtime binding')
 return value

def set_instance_update_policy(payload,*,backend,root:Path,requested_by:str)->dict[str,Any]:
 body=payload if isinstance(payload,dict) else {};instance=_instance(backend,body.get('instance_id'));runtime_id=str(instance['runtime_id']);selection=prepare_runtime_selection(root,runtime_id,'current');selection=dict(selection);selection['environment_id']=runtime_id
 _require_runtime_prerequisites(backend,str(instance['agent_id']),selection)
 repo=ServerUpdateRepository(backend);repo.initialize();return repo.set_policy(instance_id=str(instance['id']),agent_id=str(instance['agent_id']),selection=selection,policy=body.get('policy') if isinstance(body.get('policy'),dict) else {},requested_by=str(requested_by or 'system'))

def instance_update_policy_view(instance_id,*,backend)->dict[str,Any]:
 instance=_instance(backend,instance_id);iid=str(instance['id']);repo=ServerUpdateRepository(backend);repo.initialize()
 try:
  snapshot=repo.snapshot(iid);policy={key:snapshot['policy'].get(key) for key in _PUBLIC_POLICY_FIELDS};configured=True;content=snapshot.get('content') or []
 except KeyError:
  policy=normalize_policy({});configured=False;content=repo._content_snapshot(iid)
 return {'instance_id':iid,'configured':configured,'policy':policy,'content':content}

def configure_server_update(user,payload,*,backend,root:Path)->dict[str,Any]:
 actor=_require_admin(user);body=payload if isinstance(payload,dict) else {};snapshot=set_instance_update_policy(body,backend=backend,root=root,requested_by=actor);repo=ServerUpdateRepository(backend);job=repo.queue_check(str(snapshot['instance_id']),requested_by=actor)
 return {'update':snapshot,'check_job_id':job['job_id']}

def configure_content_update_policy(user,payload,*,backend)->dict[str,Any]:
 actor=_require_admin(user);body=payload if isinstance(payload,dict) else {};instance=_instance(backend,body.get('instance_id'));cid=str(body.get('content_id') or '').strip()
 if not cid or len(cid)>191:raise ValueError('valid content_id is required')
 repo=ServerUpdateRepository(backend);repo.initialize();return {'content_update_policy':repo.set_content_policy(instance_id=str(instance['id']),content_id=cid,mode=body.get('mode'),requested_by=actor)}

def server_update_status(user,instance_id,*,backend)->dict[str,Any]:
 _require_admin(user);_instance(backend,instance_id);repo=ServerUpdateRepository(backend);repo.initialize();return repo.snapshot(str(instance_id))

def server_update_operation(user,payload,*,backend)->dict[str,Any]:
 actor=_require_admin(user);body=payload if isinstance(payload,dict) else {};instance=_instance(backend,body.get('instance_id'));action=str(body.get('action') or '').strip().lower();repo=ServerUpdateRepository(backend);repo.initialize()
 if action=='check':return {'job':repo.queue_check(str(instance['id']),requested_by=actor)}
 if action=='update':return repo.queue_update(str(instance['id']),requested_by=actor,trigger_type='manual')
 raise ValueError('action must be check or update')

__all__=['configure_content_update_policy','configure_server_update','instance_update_policy_view','server_update_operation','server_update_status','set_instance_update_policy']