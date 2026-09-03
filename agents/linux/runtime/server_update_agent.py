#!/usr/bin/env python3
"""Safe Agent-side orchestration for shared game-server updates."""
from __future__ import annotations
from typing import Any, Callable
import instance_runtime
from backup_client import _create as create_backup
from server_update_provider import detect_update

def _context(selection:dict[str,Any])->tuple[str,dict[str,Any]]:
 meta=selection.get('_server_update') if isinstance(selection.get('_server_update'),dict) else {}
 iid=str(meta.get('instance_id') or '').strip()
 if not iid:raise ValueError('server update instance_id is required')
 record=instance_runtime.get_instance(iid)
 if not record:raise LookupError('server update instance not found')
 game=str(selection.get('game') or record.get('game_id') or '').strip()
 if not game or game!=str(record.get('game_id') or ''):raise ValueError('server update game identity mismatch')
 return iid,record

def _affected(config:dict[str,Any],game:str)->list[str]:
 return [str(x['instance_id']) for x in instance_runtime.list_instances(config) if str(x.get('game_id') or '')==game]

def perform_update(selection:dict[str,Any],target,installer:Callable[[],None],steamcmd:str|None=None)->dict[str,Any]:
 iid,record=_context(selection);config={'agent_id':str(record.get('agent_id') or '')};game=str(record.get('game_id') or '')
 meta=selection.get('_server_update') or {};backup_enabled=bool(meta.get('backup_before_update',True));affected=_affected(config,game)
 running=[];backups=[];restarted=[]
 before=detect_update(selection,target,steamcmd)
 if before.get('state')=='up_to_date':return {'update_status_before':before,'update_status_after':before,'affected_instances':affected,'backups':[],'restarted_instances':[],'readiness':'unchanged'}
 try:
  for current in affected:
   if instance_runtime.status(config,current).get('observed_state')=='running':
    instance_runtime.lifecycle(config,current,'stop');running.append(current)
  if backup_enabled:
   for current in affected:
    detail=create_backup(config,{'instance_id':current,'policy':{'mode':'full','compression':'gzip','retention_count':7,'consistency':'live'}})
    backups.append({'instance_id':current,'backup_id':detail.get('backup_id'),'sha256':detail.get('sha256'),'size_bytes':detail.get('size_bytes')})
  installer()
  after=detect_update(selection,target,steamcmd,force_refresh=True)
  if after.get('detector_supported') and after.get('state')!='up_to_date':raise RuntimeError('server update did not reach upstream version')
  failures=[]
  for current in running:
   try:
    instance_runtime.lifecycle(config,current,'start');restarted.append(current);doctor=instance_runtime.doctor(config,current)
    if not doctor.get('ready'):failures.append(current)
   except Exception:failures.append(current)
  if failures:raise RuntimeError('updated server failed readiness validation')
  return {'update_status_before':before,'update_status_after':after,'affected_instances':affected,'backups':backups,'restarted_instances':restarted,'readiness':'healthy','rollback_supported':False}
 except Exception:
  for current in running:
   if current in restarted:continue
   try:instance_runtime.lifecycle(config,current,'start')
   except Exception:pass
  raise

__all__=['perform_update']
