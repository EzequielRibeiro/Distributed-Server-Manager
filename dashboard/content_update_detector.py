#!/usr/bin/env python3
"""Controller-side update detection for providers that require runtime compatibility context."""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any,Mapping
from content_repository import ContentRepository
from instance_workspace_repository import InstanceWorkspaceRepository
from minecraft_content_resolver import resolve_minecraft_content
from minecraft_modpack_update_resolver import resolve_minecraft_modpack_update
from runtime_workspace_catalog import runtime_definition
from server_update_repository import ServerUpdateRepository

_STRUCTURED_PROVIDERS=frozenset({'modrinth','curseforge'})
_SUPPORTED_TYPES=frozenset({'mod','plugin','modpack'})


def _artifact_revision(artifact:Mapping[str,Any]|None)->str:
 package=str((artifact or {}).get('package_id') or '').strip()
 if ':' not in package:return ''
 project,revision=package.split(':',1)
 return revision if project and revision else ''


def _project_reference(item:Mapping[str,Any])->str:
 ctype=str(item.get('content_type') or '').strip().lower();metadata=item.get('metadata') if isinstance(item.get('metadata'),Mapping) else {};provenance=item.get('provenance') if isinstance(item.get('provenance'),Mapping) else {}
 if ctype=='modpack':
  marker=metadata.get('minecraft_modpack') if isinstance(metadata.get('minecraft_modpack'),Mapping) else {};value=str(marker.get('provider_project_id') or '').strip()
  if not value:
   marker=provenance.get('minecraft_modpack') if isinstance(provenance.get('minecraft_modpack'),Mapping) else {};value=str(marker.get('project_id') or '').strip()
 else:
  marker=provenance.get('minecraft_provider') if isinstance(provenance.get('minecraft_provider'),Mapping) else {};value=str(marker.get('project_id') or '').strip()
 if value:return value
 package=str((item.get('artifact') or {}).get('package_id') or '').strip()
 return package.split(':',1)[0] if ':' in package else package


def _bundle_child(item:Mapping[str,Any])->bool:
 metadata=item.get('metadata') if isinstance(item.get('metadata'),Mapping) else {};marker=metadata.get('bundle') if isinstance(metadata.get('bundle'),Mapping) else {}
 return bool(marker.get('parent_content_id')) and str(item.get('content_type') or '').lower()!='modpack'


class ControllerContentUpdateDetector:
 def __init__(self,backend,root:Path,*,content=None,instances=None,state=None,resolver=None,modpack_resolver=None,interval_seconds:int=900):
  self.backend=backend;self.root=Path(root);self.content=content or ContentRepository(backend);self.instances=instances or InstanceWorkspaceRepository(backend);self.state=state or ServerUpdateRepository(backend);self.resolver=resolver or resolve_minecraft_content;self.modpack_resolver=modpack_resolver or resolve_minecraft_modpack_update;self.interval_seconds=max(60,min(int(interval_seconds),86400));self._last_scan_monotonic=0.0
  self.content.initialize();self.instances.initialize();self.state.initialize()
 def scan(self,*,limit:int=500,force:bool=False)->dict[str,int]:
  now=time.monotonic()
  if not force and self._last_scan_monotonic and now-self._last_scan_monotonic<self.interval_seconds:return {'checked':0,'available':0,'current':0,'failed':0,'skipped':0}
  checked=available=current=failed=skipped=0;grouped:dict[str,list[dict[str,Any]]]={}
  for item in self.content.list(desired_state='installed',limit=max(1,min(int(limit),2000))):
   provider=str(item.get('provider') or '').strip().lower();ctype=str(item.get('content_type') or '').strip().lower();metadata=item.get('metadata') if isinstance(item.get('metadata'),Mapping) else {};revision_source=metadata.get('revision_source') if isinstance(metadata.get('revision_source'),Mapping) else {}
   if ctype=='modpack' and str(revision_source.get('kind') or '').strip().lower()=='external-upload':skipped+=1;continue
   if provider not in _STRUCTURED_PROVIDERS:continue
   if ctype not in _SUPPORTED_TYPES or _bundle_child(item):skipped+=1;continue
   iid=str(item.get('instance_id') or '');cid=str(item.get('content_id') or '');aid=str(item.get('agent_id') or '')
   if not iid or not cid or not aid:skipped+=1;continue
   checked+=1;base={'instance_id':iid,'content_id':cid,'provider':provider,'content_type':ctype,'detector_supported':True,'rollback_supported':True}
   try:
    context=self.instances.instance_context(iid);game=str(context.get('game_id') or '').strip().lower();runtime_id=str(context.get('runtime_id') or '').strip();game_version=str(context.get('game_version') or '').strip()
    if game!='minecraft' or not runtime_id or not game_version:raise ValueError('structured content runtime identity is unavailable')
    definition=runtime_definition(self.root,game,runtime_id)
    if not definition:raise ValueError('runtime definition is unavailable')
    project=_project_reference(item)
    if not project:raise ValueError('provider project identity is unavailable')
    if ctype=='modpack':
     identity=self.modpack_resolver(provider,project,game_version,definition);candidate={'provider':provider,'package_id':str(identity.get('package_id') or '')}
    else:
     resolved=self.resolver(provider,project,game_version,definition,ctype);candidate=resolved.get('artifact') if isinstance(resolved,Mapping) else None
    installed_artifact=item.get('artifact') if isinstance(item.get('artifact'),Mapping) else {};installed_revision=_artifact_revision(installed_artifact);candidate_revision=_artifact_revision(candidate if isinstance(candidate,Mapping) else {})
    if not installed_revision or not candidate_revision:raise ValueError('provider revision identity is unavailable')
    status='up_to_date' if str(installed_artifact.get('package_id') or '')==str((candidate or {}).get('package_id') or '') else 'update_available'
    if status=='update_available':available+=1
    else:current+=1
    grouped.setdefault(aid,[]).append({**base,'state':status,'installed_revision':installed_revision,'available_revision':candidate_revision})
   except Exception as exc:
    failed+=1;grouped.setdefault(aid,[]).append({**base,'state':'probe_failed','installed_revision':_artifact_revision(item.get('artifact') if isinstance(item.get('artifact'),Mapping) else {}),'available_revision':None,'error':str(exc)[:2000]})
  for aid,items in grouped.items():self.state.record_content_update_inventory(aid,{'kind':'ContentUpdateInventory','content':items})
  self._last_scan_monotonic=now
  return {'checked':checked,'available':available,'current':current,'failed':failed,'skipped':skipped}


__all__=['ControllerContentUpdateDetector','_artifact_revision','_project_reference']
