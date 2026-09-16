#!/usr/bin/env python3
"""M4 policy worker: convert detected managed-content updates into canonical U9 revisions."""
from __future__ import annotations
import os,re,sys,time
from pathlib import Path
from typing import Any
ROOT=Path(os.environ.get('DSM_ROOT',Path(__file__).resolve().parents[2])).resolve()
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from content_update_dispatch_repository import ContentUpdateDispatchRepository
from customer_content_workspace import CustomerContentWorkspaceService
from runtime_backend import backend_from_environment

INTERVAL_SECONDS=max(10,int(os.environ.get('DSM_CONTENT_UPDATE_WORKER_SECONDS','30')))
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


class ContentUpdateWorker:
 def __init__(self,backend,root:Path=ROOT,*,repository=None,service=None):
  self.backend=backend;self.root=Path(root);self.repository=repository or ContentUpdateDispatchRepository(backend);self.repository.initialize();self.service=service or CustomerContentWorkspaceService(backend,self.root)
 def tick(self,limit:int=200)->dict[str,Any]:
  due=self.repository.due(limit=limit);result={'due':len(due),'claimed':0,'updated':0,'unchanged':0,'failed':0,'instances':{}}
  for item in due:
   iid=str(item.get('instance_id') or '');cid=str(item.get('content_id') or '')
   if not self.repository.claim(item):continue
   result['claimed']+=1;result['instances'][iid]=result['instances'].get(iid,0)+1
   try:
    mutation=self.service.mutate(ACTOR,iid,cid,'update',{})
    current=self.service.content.get(iid,cid)
    revision=int((current or {}).get('revision') or 0)
    if revision<1:raise RuntimeError('updated content assignment is unavailable')
    self.repository.complete(item,revision)
    changed=bool(mutation.get('changed',True)) if isinstance(mutation,dict) else True
    result['updated' if changed else 'unchanged']+=1
   except Exception as exc:
    self.repository.fail(item,exc);result['failed']+=1
  return result


def run_forever(root:Path=ROOT,interval:int=INTERVAL_SECONDS)->None:
 backend=backend_from_environment(_database_environment(root));worker=ContentUpdateWorker(backend,root)
 while True:
  try:
   report=worker.tick()
   if report['due'] or report['failed']:print(f"content update worker due={report['due']} claimed={report['claimed']} updated={report['updated']} unchanged={report['unchanged']} failed={report['failed']} instances={len(report['instances'])}",flush=True)
  except Exception as exc:print(f'content update worker failed: {exc}',file=sys.stderr,flush=True)
  time.sleep(max(10,int(interval)))


if __name__=='__main__':run_forever()
