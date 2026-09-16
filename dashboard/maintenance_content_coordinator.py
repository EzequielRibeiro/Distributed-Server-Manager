#!/usr/bin/env python3
"""M5 bridge from maintenance events to canonical M4/U9 content revisions."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from content_update_dispatch_repository import ContentUpdateDispatchRepository
from content_update_validation import verify_content_update_revision
from customer_content_workspace import CustomerContentWorkspaceService
from maintenance_configuration_coordinator import MaintenanceConfigurationCoordinator

ACTOR={'role':'admin','username':'maintenance-worker'}


class MaintenanceContentCoordinator:
 def __init__(self,backend,root:Path):
  self.dispatch=ContentUpdateDispatchRepository(backend);self.dispatch.initialize();self.service=CustomerContentWorkspaceService(backend,Path(root));self.configuration=MaintenanceConfigurationCoordinator(backend)
 def discover(self,instance_id:str,*,limit:int=200)->list[dict[str,Any]]:
  values=[{'kind':'content-update','ref':str(item.get('content_id') or ''),'available_version':str(item.get('available_version') or ''),'status':'pending'} for item in self.dispatch.due_for_maintenance(str(instance_id),limit=limit) if str(item.get('content_id') or '').strip()]
  configuration=getattr(self,'configuration',None)
  if configuration is not None:values.extend(configuration.discover(str(instance_id)))
  return values
 def dispatch_pending(self,instance_id:str,pending_work:list[dict[str,Any]])->list[dict[str,Any]]:
  iid=str(instance_id);fresh={str(item.get('content_id') or ''):item for item in self.dispatch.due_for_maintenance(iid,limit=max(200,len(pending_work)*2))};result=[]
  for raw in pending_work:
   item=dict(raw)
   if item.get('kind')!='content-update':result.append(item);continue
   if int(item.get('desired_revision') or 0)>0 or item.get('status') in {'aligned','failed','skipped'}:result.append(item);continue
   cid=str(item.get('ref') or '');candidate=fresh.get(cid)
   if candidate is None:
    item['status']='skipped';item['error']='update is no longer pending';result.append(item);continue
   if not self.dispatch.claim(candidate):
    item['status']='pending';result.append(item);continue
   try:
    self.service.mutate(ACTOR,iid,cid,'update',{})
    revision=verify_content_update_revision(candidate,self.service.content.get(iid,cid));self.dispatch.complete(candidate,revision);item['desired_revision']=revision;item['status']='dispatched';item.pop('error',None)
   except Exception as exc:
    self.dispatch.fail(candidate,exc);item['status']='failed';item['error']=str(exc).replace('\x00','')[:500]
   result.append(item)
  return result
 def alignment(self,instance_id:str,pending_work:list[dict[str,Any]])->dict[str,Any]:
  iid=str(instance_id);works=[dict(item) for item in pending_work];expected={str(item.get('ref')):int(item.get('desired_revision')) for item in works if item.get('kind')=='content-update' and int(item.get('desired_revision') or 0)>0 and item.get('status')!='failed'};failed=[item for item in works if item.get('kind')=='content-update' and item.get('status')=='failed']
  content_items=[item for item in works if item.get('kind')=='content-update']
  if failed:return {'ready':False,'pending':[], 'failed':failed,'work':works}
  if content_items:
   view=self.dispatch.alignment(iid,expected);aligned=set(view.get('aligned') or []);failed_by_id={str(item.get('content_id')):item for item in view.get('failed') or []}
   for item in works:
    if item.get('kind')!='content-update':continue
    cid=str(item.get('ref') or '')
    if cid in aligned:item['status']='aligned';item.pop('error',None)
    elif cid in failed_by_id:item['status']='failed';item['error']=str(failed_by_id[cid].get('error') or 'content reconciliation failed')[:500]
   failures=[item for item in works if item.get('kind')=='content-update' and item.get('status')=='failed']
   content_ready=bool(view.get('ready')) and not failures;content_pending=list(view.get('pending') or []);content_aligned=list(view.get('aligned') or [])
  else:
   failures=[];content_ready=True;content_pending=[];content_aligned=[]
  configuration=getattr(self,'configuration',None)
  if configuration is not None:
   config_view=configuration.alignment(iid,works);works=config_view.get('work') or works;config_ready=bool(config_view.get('ready'));config_pending=list(config_view.get('pending') or []);config_failed=list(config_view.get('failed') or []);config_aligned=list(config_view.get('aligned') or [])
  else:
   config_ready=True;config_pending=[];config_failed=[];config_aligned=[]
  all_failures=failures+config_failed
  return {'ready':content_ready and config_ready and not all_failures,'pending':content_pending+config_pending,'failed':all_failures,'aligned':content_aligned+config_aligned,'work':works}


__all__=['MaintenanceContentCoordinator']
