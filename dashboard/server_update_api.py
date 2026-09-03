#!/usr/bin/env python3
"""Controller API for universal game-server update policy and operations."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from alert_repository import AlertSession,dialect_for_backend
from agent_game_data_api import prepare_runtime_selection,_require_runtime_prerequisites
from server_update_repository import ServerUpdateRepository

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

def configure_server_update(user,payload,*,backend,root:Path)->dict[str,Any]:
 actor=_require_admin(user);body=payload if isinstance(payload,dict) else {};instance=_instance(backend,body.get('instance_id'))
 runtime_id=str(instance['runtime_id']);selection=prepare_runtime_selection(root,runtime_id,'current');selection=dict(selection);selection['environment_id']=runtime_id
 _require_runtime_prerequisites(backend,str(instance['agent_id']),selection)
 repo=ServerUpdateRepository(backend);repo.initialize();snapshot=repo.set_policy(instance_id=str(instance['id']),agent_id=str(instance['agent_id']),selection=selection,policy=body.get('policy') if isinstance(body.get('policy'),dict) else {},requested_by=actor);job=repo.queue_check(str(instance['id']),requested_by=actor)
 return {'update':snapshot,'check_job_id':job['job_id']}

def server_update_status(user,instance_id,*,backend)->dict[str,Any]:
 _require_admin(user);_instance(backend,instance_id);repo=ServerUpdateRepository(backend);repo.initialize();return repo.snapshot(str(instance_id))

def server_update_operation(user,payload,*,backend)->dict[str,Any]:
 actor=_require_admin(user);body=payload if isinstance(payload,dict) else {};instance=_instance(backend,body.get('instance_id'));action=str(body.get('action') or '').strip().lower();repo=ServerUpdateRepository(backend);repo.initialize()
 if action=='check':return {'job':repo.queue_check(str(instance['id']),requested_by=actor)}
 if action=='update':return repo.queue_update(str(instance['id']),requested_by=actor,trigger_type='manual')
 raise ValueError('action must be check or update')

__all__=['configure_server_update','server_update_operation','server_update_status']
