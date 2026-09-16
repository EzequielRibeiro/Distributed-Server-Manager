#!/usr/bin/env python3
"""M5 controller worker for scheduled maintenance warnings, restart and readiness."""
from __future__ import annotations
import os,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(os.environ.get('DSM_ROOT',Path(__file__).resolve().parents[2])).resolve()
for path in (ROOT,ROOT/'core',ROOT/'database'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository,InstanceLifecycleCommandConflict
from automation_repository import AutomationRepository
from maintenance_platform import due_warning_offsets,render_warning
from maintenance_repository import MaintenanceRepository
from runtime_backend import backend_from_environment
INTERVAL_SECONDS=max(1,min(int(os.environ.get('DSM_MAINTENANCE_WORKER_SECONDS','5')),60))
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

def _dt(value)->datetime:return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(timezone.utc)
def _doctor_ready(command:dict)->bool:
 outer=command.get('result') if isinstance(command.get('result'),dict) else {};payload=outer.get('result') if isinstance(outer.get('result'),dict) else {};return bool(payload.get('ready'))

class MaintenanceWorker:
 def __init__(self,backend,*,repository=None,automation=None,lifecycle=None):
  self.backend=backend;self.repository=repository or MaintenanceRepository(backend);self.repository.initialize();self.automation=automation or AutomationRepository(backend);self.automation.initialize();self.lifecycle=lifecycle or AgentInstanceRuntimeRepository(backend);self.lifecycle.initialize()
 def _warning(self,run:dict,policy:dict,offset:int)->None:
  ttl=max(60,min(int(offset),3600));item=self.automation.create_broadcast({'scope':'instance','target':str(run['instance_id']),'message':render_warning(policy,offset),'priority':'high','ttl_seconds':ttl,'require_ack':False},requested_by='maintenance-worker');self.repository.record_warning(str(run['run_id']),offset,str(item['broadcast_id']))
 def _restart(self,run:dict)->None:
  command=self.lifecycle.enqueue(agent_id=str(run['agent_id']),instance_id=str(run['instance_id']),action='restart',requested_by='maintenance-worker');self.repository.mark_restart(str(run['run_id']),str(command['command_id']))
 def _readiness(self,run:dict)->None:
  command=self.lifecycle.enqueue(agent_id=str(run['agent_id']),instance_id=str(run['instance_id']),action='doctor',requested_by='maintenance-worker');self.repository.mark_readiness(str(run['run_id']),str(command['command_id']))
 def _advance(self,run:dict,now:datetime,result:dict)->None:
  iid=str(run['instance_id']);rid=str(run['run_id']);policy=self.repository.policy(iid);due=_dt(run['due_at'])
  if now<due:
   sent={int(value) for value in (run.get('warnings_sent') or [])}
   for offset in due_warning_offsets(policy,due,now=now,sent_offsets=sent):
    try:self._warning(run,policy,offset);result['warnings']+=1;sent.add(offset)
    except Exception as exc:result['warning_failures'].append({'run_id':rid,'offset_seconds':offset,'error':str(exc)[:500]})
   return
  if not run.get('lifecycle_command_id'):
   try:self._restart(run);result['restarts']+=1
   except InstanceLifecycleCommandConflict:return
   except Exception as exc:self.repository.finish(rid,success=False,error_code='restart_enqueue_failed',error_detail=str(exc),now=now);result['failed']+=1
   return
  command=self.lifecycle.snapshot(str(run['lifecycle_command_id']));status=str(command.get('status') or '')
  if status in {'queued','delivered'}:return
  if status!='completed':self.repository.finish(rid,success=False,error_code='restart_failed',error_detail=command.get('last_error') or 'restart failed',now=now);result['failed']+=1;return
  if not run.get('readiness_command_id'):
   try:self._readiness(run)
   except Exception as exc:self.repository.finish(rid,success=False,error_code='readiness_enqueue_failed',error_detail=str(exc),now=now);result['failed']+=1
   return
  doctor=self.lifecycle.snapshot(str(run['readiness_command_id']));doctor_status=str(doctor.get('status') or '')
  if doctor_status in {'queued','delivered'}:return
  if doctor_status=='completed' and _doctor_ready(doctor):self.repository.finish(rid,success=True,now=now);result['completed']+=1
  else:self.repository.finish(rid,success=False,error_code='readiness_failed',error_detail=doctor.get('last_error') or 'instance is not ready after restart',now=now);result['failed']+=1
 def tick(self,*,now:datetime|None=None)->dict:
  current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc);result={'planned':0,'active':0,'warnings':0,'restarts':0,'completed':0,'failed':0,'warning_failures':[]}
  for iid in self.repository.candidates(now=current):
   try:
    if self.repository.ensure_run(iid,now=current):result['planned']+=1
   except Exception:continue
  runs=self.repository.active_runs();result['active']=len(runs)
  for run in runs:
   try:self._advance(run,current,result)
   except Exception as exc:
    try:self.repository.finish(str(run['run_id']),success=False,error_code='worker_error',error_detail=str(exc),now=current);result['failed']+=1
    except Exception:pass
  return result

def run_forever(interval:int=INTERVAL_SECONDS)->None:
 backend=backend_from_environment(_database_environment(ROOT));worker=MaintenanceWorker(backend)
 while True:
  try:
   result=worker.tick()
   if result['active'] or result['failed']:print(f"maintenance worker active={result['active']} planned={result['planned']} warnings={result['warnings']} restarts={result['restarts']} completed={result['completed']} failed={result['failed']}",flush=True)
  except Exception as exc:print(f'maintenance worker failed: {exc}',file=sys.stderr,flush=True)
  time.sleep(max(1,int(interval)))
if __name__=='__main__':run_forever()
