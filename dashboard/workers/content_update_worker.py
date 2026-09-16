#!/usr/bin/env python3
"""M4 policy worker: detect and convert managed-content updates into canonical U9 revisions."""
from __future__ import annotations
import os,re,sys,time
from pathlib import Path
from typing import Any
ROOT=Path(os.environ.get('DSM_ROOT',Path(__file__).resolve().parents[2])).resolve()
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from content_update_detector import ControllerContentUpdateDetector,_artifact_revision
from content_update_dispatch_repository import ContentUpdateDispatchRepository
from customer_content_workspace import CustomerContentWorkspaceService
from runtime_backend import backend_from_environment

INTERVAL_SECONDS=max(10,int(os.environ.get('DSM_CONTENT_UPDATE_WORKER_SECONDS','30')))
DETECTION_INTERVAL_SECONDS=max(60,min(int(os.environ.get('DSM_CONTENT_UPDATE_DETECT_SECONDS','900')),86400))
ACTOR={'role':'admin','username':'content-update-worker'}
_ALLOWED_DB_KEYS={'DSM_DATABASE_DRIVER','DSM_DATABASE','DSM_DATABASE_HOST','DSM_DATABASE_PORT','DSM_DATABASE_NAME','DSM_DATABASE_USER','DSM_DATABASE_PASSWORD_FILE','DSM_DATABASE_TLS'}


def _read_shell_values(path:Path)->dict[str,str]:
 if not path.is_file():return {}
 result={};pattern=re.compile(r'^([A-Z0-9_]+)=(?:"([^"]*)"|\'([^\']*)\'|([^#\s]*))\s*$')
 for raw in path.read_text(encoding='utf-8').splitlines():
  line=raw.strip()
  if not line or line.startswith('#'):continue
  match=pattern.match(line)
  if match:result[match.group(1)]=next((value for value in match.groups()[1:] if value is not None),'')
 return result


def _database_environment(root:Path=ROOT,environment:dict[str,str]|None=None)->dict[str,str]:
 effective=dict(os.environ if environment is None else environment)
 for key,value in _read_shell_values(root/'config'/'dsm.conf').items():
  if key in _ALLOWED_DB_KEYS and key not in effective:effective[key]=value
 effective.setdefault('DSM_ROOT',str(root));return effective


def _verify_applied_revision(item:dict[str,Any],current:dict[str,Any]|None)->int:
 value=current if isinstance(current,dict) else {};before=int(item.get('assignment_revision') or 0);after=int(value.get('revision') or 0)
 if after<=before:raise RuntimeError('content update did not create a new canonical revision')
 provider=str(item.get('provider') or '').strip().lower();available=str(item.get('available_version') or '').strip()
 if provider in {'steam','steam-workshop'}:
  resolved=str(value.get('version') or '').strip()
  if not available or resolved!=available:raise RuntimeError('Steam Workshop canonical revision does not match detected upstream revision')
 elif provider in {'modrinth','curseforge'}:
  resolved=_artifact_revision(value.get('artifact') if isinstance(value.get('artifact'),dict) else {})
  if not available or resolved!=available:raise RuntimeError('structured provider canonical revision does not match detected upstream revision')
 return after


class ContentUpdateWorker:
 def __init__(self,backend,root:Path=ROOT,*,repository=None,service=None,detector=None):
  self.backend=backend;self.root=Path(root);self.repository=repository or ContentUpdateDispatchRepository(backend);self.repository.initialize();self.service=service or CustomerContentWorkspaceService(backend,self.root);self.detector=detector or ControllerContentUpdateDetector(backend,self.root,interval_seconds=DETECTION_INTERVAL_SECONDS)
 def tick(self,limit:int=200)->dict[str,Any]:
  detector=getattr(self,'detector',None);detection=detector.scan(limit=max(limit,500)) if detector is not None else {'checked':0,'available':0,'current':0,'failed':0,'skipped':0}
  due=self.repository.due(limit=limit);result={'detection':detection,'due':len(due),'claimed':0,'updated':0,'failed':0,'instances':{}}
  for item in due:
   iid=str(item.get('instance_id') or '');cid=str(item.get('content_id') or '')
   if not self.repository.claim(item):continue
   result['claimed']+=1;result['instances'][iid]=result['instances'].get(iid,0)+1
   try:
    self.service.mutate(ACTOR,iid,cid,'update',{})
    revision=_verify_applied_revision(item,self.service.content.get(iid,cid))
    self.repository.complete(item,revision);result['updated']+=1
   except Exception as exc:
    self.repository.fail(item,exc);result['failed']+=1
  return result


def run_forever(root:Path=ROOT,interval:int=INTERVAL_SECONDS)->None:
 backend=backend_from_environment(_database_environment(root));worker=ContentUpdateWorker(backend,root)
 while True:
  try:
   report=worker.tick();detection=report.get('detection') or {}
   if report['due'] or report['failed'] or detection.get('checked'):print(f"content update worker detected={detection.get('checked',0)} available={detection.get('available',0)} due={report['due']} claimed={report['claimed']} updated={report['updated']} failed={report['failed']} instances={len(report['instances'])}",flush=True)
  except Exception as exc:print(f'content update worker failed: {exc}',file=sys.stderr,flush=True)
  time.sleep(max(10,int(interval)))


if __name__=='__main__':run_forever()
