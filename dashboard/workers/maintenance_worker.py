#!/usr/bin/env python3
"""M5 controller worker for warnings, coalesced work, stop/start and readiness."""
from __future__ import annotations
import os,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(os.environ.get('DSM_ROOT',Path(__file__).resolve().parents[2])).resolve()
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository,InstanceLifecycleCommandConflict
from dayz_native_restart_repository import DayZNativeRestartRepository,DayZNativeRestartCommandConflict
from automation_repository import AutomationRepository
from maintenance_content_coordinator import MaintenanceContentCoordinator
from maintenance_game_update_coordinator import MaintenanceGameUpdateCoordinator
from maintenance_platform import due_warning_offsets,maintenance_event,render_warning,update_maintenance_event
from maintenance_repository import MaintenanceRepository
from runtime_backend import backend_from_environment
from runtime_workspace_catalog import runtime_workspace_capabilities
INTERVAL_SECONDS=max(1,min(int(os.environ.get('DSM_MAINTENANCE_WORKER_SECONDS','5')),60))
NATIVE_SHUTDOWN_TIMEOUT_SECONDS=max(30,min(int(os.environ.get('DSM_DAYZ_NATIVE_SHUTDOWN_TIMEOUT_SECONDS','180')),900))
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
def _payload(command:dict)->dict:
 outer=command.get('result') if isinstance(command.get('result'),dict) else {};payload=outer.get('result') if isinstance(outer.get('result'),dict) else {};return payload
def _doctor_ready(command:dict)->bool:return bool(_payload(command).get('ready'))
def _observed_state(command:dict)->str:return str(_payload(command).get('observed_state') or 'unknown').strip().lower()
def _work_key(item:dict)->tuple[str,str]:return str(item.get('kind') or ''),str(item.get('ref') or '')

class MaintenanceWorker:
 def __init__(self,backend,root:Path=ROOT,*,repository=None,automation=None,lifecycle=None,capability_resolver=None,content_coordinator=None,game_coordinator=None):
  self.backend=backend;self.root=Path(root);self.repository=repository or MaintenanceRepository(backend);self.repository.initialize();self.automation=automation or AutomationRepository(backend);self.automation.initialize();self.lifecycle=lifecycle or AgentInstanceRuntimeRepository(backend);self.lifecycle.initialize();self.native_restart=DayZNativeRestartRepository(backend) if backend is not None else None;self.native_restart.initialize() if self.native_restart is not None else None;self.capability_resolver=capability_resolver;self.content=content_coordinator if content_coordinator is not None else (MaintenanceContentCoordinator(backend,self.root) if backend is not None else None);self.game=game_coordinator if game_coordinator is not None else (MaintenanceGameUpdateCoordinator(backend) if backend is not None else None)
 def _capabilities(self,instance_id:str)->dict:
  if self.capability_resolver is not None:return dict(self.capability_resolver(instance_id) or {})
  context=self.repository.instance_context(instance_id);game=str(context.get('game_id') or '').strip();runtime=str(context.get('runtime_id') or '').strip()
  if not game or not runtime:return {'scheduled_restart':False}
  return dict((runtime_workspace_capabilities(self.root,game,runtime).get('maintenance') or {}))
 def _discover_work(self,instance_id:str,policy:dict)->list[dict]:
  if not policy.get('coalesce_updates'):return []
  result=[]
  if self.game is not None:
   try:result.extend(self.game.discover(instance_id))
   except Exception:pass
  if self.content is not None:
   try:result.extend(self.content.discover(instance_id))
   except Exception:pass
  return result
 def _ensure_event(self,run:dict,policy:dict)->dict:
  if isinstance(run.get('event'),dict) and run['event'].get('kind')=='CapivaraMaintenanceEvent':return run
  pending=self._discover_work(str(run['instance_id']),policy);event=maintenance_event(policy,self._capabilities(str(run['instance_id'])),pending_work=pending);return self.repository.set_event(str(run['run_id']),event)
 def _refresh_event_work(self,run:dict,policy:dict)->dict:
  if not policy.get('coalesce_updates'):return run
  event=dict(run.get('event') or {});existing=[dict(item) for item in event.get('pending_work') or [] if isinstance(item,dict)];discovered=self._discover_work(str(run['instance_id']),policy);merged={_work_key(item):item for item in existing}
  for item in discovered:
   key=_work_key(item)
   if key not in merged:merged[key]=dict(item)
  if len(merged)==len(existing):return run
  refreshed=maintenance_event(policy,event.get('capabilities') or self._capabilities(str(run['instance_id'])),pending_work=list(merged.values()))
  if event.get('work_error'):refreshed['work_error']=event.get('work_error')
  if isinstance(event.get('recovery'),dict):refreshed['recovery']=dict(event['recovery'])
  return self.repository.update_event(str(run['run_id']),refreshed)
 def _warning(self,run:dict,policy:dict,offset:int)->None:
  ttl=max(60,min(int(offset),3600));item=self.automation.create_broadcast({'scope':'instance','target':str(run['instance_id']),'message':render_warning(policy,offset),'priority':'high','ttl_seconds':ttl,'require_ack':False},requested_by='maintenance-worker');self.repository.record_warning(str(run['run_id']),offset,str(item['broadcast_id']))
 def _enqueue(self,run:dict,action:str,marker)->dict:
  command=self.lifecycle.enqueue(agent_id=str(run['agent_id']),instance_id=str(run['instance_id']),action=action,requested_by='maintenance-worker');owner=str(command.get('requested_by') or '')
  if owner and owner!='maintenance-worker':raise RuntimeError(f'instance has concurrent {action} command owned by {owner}')
  return marker(str(run['run_id']),str(command['command_id']))
 def _raw_lifecycle(self,run:dict,action:str)->dict:
  command=self.lifecycle.enqueue(agent_id=str(run['agent_id']),instance_id=str(run['instance_id']),action=action,requested_by='maintenance-worker');owner=str(command.get('requested_by') or '')
  if owner and owner!='maintenance-worker':raise RuntimeError(f'instance has concurrent {action} command owned by {owner}')
  return command
 def _command(self,command_id)->dict|None:
  if not command_id:return None
  return self.lifecycle.snapshot(str(command_id))
 def _failed(self,run:dict,code:str,command:dict,now:datetime,result:dict)->None:
  self.repository.finish(str(run['run_id']),success=False,error_code=code,error_detail=command.get('last_error') or command.get('error') or code,now=now);result['failed']+=1
 def _apply_game_work(self,run:dict,event:dict,result:dict)->tuple[dict,bool]:
  if self.game is None:return event,True
  works=[dict(item) for item in event.get('pending_work') or [] if isinstance(item,dict)];indices=[index for index,item in enumerate(works) if item.get('kind')=='game-update']
  if not indices:return event,True
  waiting=False;failed=[]
  for index in indices:
   item,ready=self.game.prepare(str(run['instance_id']),works[index]);works[index]=item
   if item.get('status')=='activated':result['game_activated']+=1
   if item.get('status')=='failed':failed.append(item)
   if not ready:waiting=True
  event=update_maintenance_event(event,pending_work=works)
  if failed:
   message='; '.join(f"{item.get('ref')}: {item.get('error') or 'game update failed'}" for item in failed)[:1000];event=update_maintenance_event(event,work_error=message);self.repository.update_event(str(run['run_id']),event,stage='work-failed');result['game_failed']+=len(failed);return event,True
  self.repository.update_event(str(run['run_id']),event,stage='applying-updates' if waiting else 'game-update-activated')
  if waiting:result['game_waiting']+=1;return event,False
  return event,True
 def _apply_content_work(self,run:dict,event:dict,result:dict)->tuple[dict,bool]:
  if self.content is None:return event,True
  pending=[dict(item) for item in event.get('pending_work') or [] if isinstance(item,dict)];content=[item for item in pending if item.get('kind')=='content-update']
  if not content:return event,True
  before={_work_key(item):int(item.get('desired_revision') or 0) for item in content};updated=self.content.dispatch_pending(str(run['instance_id']),pending);dispatched=sum(1 for item in updated if item.get('kind')=='content-update' and int(item.get('desired_revision') or 0)>before.get(_work_key(item),0));result['content_dispatched']+=dispatched
  event=update_maintenance_event(event,pending_work=updated);self.repository.update_event(str(run['run_id']),event,stage='applying-updates')
  undispatched=[item for item in updated if item.get('kind')=='content-update' and item.get('status')=='pending' and not int(item.get('desired_revision') or 0)]
  if undispatched:result['content_waiting']+=len(undispatched);return event,False
  aligned=self.content.alignment(str(run['instance_id']),updated);event=update_maintenance_event(event,pending_work=aligned.get('work') or updated)
  if aligned.get('failed'):
   message='; '.join(f"{item.get('ref')}: {item.get('error') or 'content update failed'}" for item in aligned['failed'])[:1000];event=update_maintenance_event(event,work_error=message);self.repository.update_event(str(run['run_id']),event,stage='work-failed');result['content_failed']+=len(aligned['failed']);return event,True
  self.repository.update_event(str(run['run_id']),event,stage='applying-updates' if not aligned.get('ready') else 'updates-applied')
  if not aligned.get('ready'):result['content_waiting']+=len(aligned.get('pending') or []);return event,False
  result['content_aligned']+=len(aligned.get('aligned') or []);return event,True
 def _native_command_for_current_due(self,run:dict,event:dict)->dict|None:
  capabilities=event.get('capabilities') if isinstance(event.get('capabilities'),dict) else {}
  if not capabilities.get('native_countdown') or self.native_restart is None:return None
  try:return self.native_restart.for_instance_due(str(run['instance_id']),run['due_at'])
  except Exception:return None

 def _wait_native_shutdown(self,run:dict,event:dict,now:datetime,result:dict)->tuple[dict,bool]:
  rid=str(run['run_id']);state=dict(event.get('native_shutdown') or {})
  started=str(state.get('started_at') or '')
  if not started:
   started=now.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
   state['started_at']=started
  try:started_at=_dt(started)
  except Exception:started_at=now
  if (now-started_at).total_seconds()>=NATIVE_SHUTDOWN_TIMEOUT_SECONDS:
   event=dict(event);event['native_shutdown']={**state,'status':'timeout'}
   self.repository.update_event(rid,event,stage='native-shutdown-timeout')
   self.repository.finish(
    rid,
    success=False,
    error_code='native_shutdown_timeout',
    error_detail=f'DayZ did not complete native shutdown within {NATIVE_SHUTDOWN_TIMEOUT_SECONDS} seconds',
    now=now,
   )
   result['native_shutdown_timeouts']+=1;result['failed']+=1
   return event,False
  command_id=str(state.get('command_id') or '')
  if not command_id:
   try:command=self._raw_lifecycle(run,'status')
   except InstanceLifecycleCommandConflict:return event,False
   state['command_id']=str(command['command_id']);state['status']='checking'
   event=dict(event);event['native_shutdown']=state
   self.repository.update_event(rid,event,stage='awaiting-native-shutdown')
   result['native_shutdown_checks']+=1
   return event,False
  command=self._command(command_id);status=str((command or {}).get('status') or '').lower()
  if status in {'queued','delivered'}:return event,False
  if status!='completed':
   self.repository.finish(
    rid,
    success=False,
    error_code='native_shutdown_status_failed',
    error_detail=str((command or {}).get('last_error') or 'native shutdown status check failed'),
    now=now,
   )
   result['failed']+=1
   return event,False
  observed=_observed_state(command or {})
  if observed=='stopped':
   event=dict(event);event['native_shutdown']={**state,'status':'completed','command_id':command_id}
   self.repository.update_event(rid,event,stage='native-shutdown-completed')
   result['native_shutdowns']+=1
   return event,True
  state['command_id']=None;state['status']='waiting';state['observed_state']=observed
  event=dict(event);event['native_shutdown']=state
  self.repository.update_event(rid,event,stage='awaiting-native-shutdown')
  return event,False

 def _prepare_next_native_restart(self,run:dict,event:dict,now:datetime,result:dict)->tuple[dict,bool]:
  capabilities=event.get('capabilities') if isinstance(event.get('capabilities'),dict) else {}
  if not capabilities.get('native_countdown'):return event,True
  if self.native_restart is None:return event,False
  state=dict(event.get('native_restart') or {})
  command_id=str(state.get('command_id') or '')
  if not command_id:
   due=self.repository.next_due_for_run(str(run['run_id']),now=now)
   if due is None:return event,True
   try:
    command=self.native_restart.enqueue(agent_id=str(run['agent_id']),instance_id=str(run['instance_id']),due_at=due,requested_by='maintenance-worker')
   except DayZNativeRestartCommandConflict:
    return event,False
   state={'command_id':str(command['command_id']),'due_at':due.isoformat().replace('+00:00','Z'),'status':str(command.get('status') or 'queued')}
   event=dict(event);event['native_restart']=state
   self.repository.update_event(str(run['run_id']),event,stage='preparing-native-restart')
   result['native_restart_prepared']+=1
   return event,False
  try:command=self.native_restart.snapshot(command_id)
  except Exception as exc:
   event=dict(event);event['native_restart']={**state,'status':'failed','error':str(exc)[:500]}
   self.repository.update_event(str(run['run_id']),event,stage='native-restart-failed')
   return event,True
  status=str(command.get('status') or '').lower()
  state={**state,'status':status}
  event=dict(event);event['native_restart']=state
  self.repository.update_event(str(run['run_id']),event,stage='preparing-native-restart' if status in {'queued','delivered'} else 'native-restart-prepared')
  if status in {'queued','delivered'}:return event,False
  if status!='completed':
   event['work_error']=str(command.get('last_error') or 'native restart preparation failed')[:1000]
   self.repository.update_event(str(run['run_id']),event,stage='native-restart-failed')
   return event,True
  return event,True

 def _finalize_game_work(self,run:dict,event:dict,result:dict)->tuple[dict,bool]:
  if self.game is None:return event,True
  works=[dict(item) for item in event.get('pending_work') or [] if isinstance(item,dict)];indices=[i for i,item in enumerate(works) if item.get('kind')=='game-update' and item.get('transaction_id')]
  if not indices:return event,True
  waiting=False;failed=[]
  for index in indices:
   item,ready=self.game.finalize(str(run['instance_id']),works[index]);works[index]=item
   if item.get('status')=='committed':result['game_committed']+=1
   if item.get('status')=='failed':failed.append(item)
   if not ready:waiting=True
  event=update_maintenance_event(event,pending_work=works);self.repository.update_event(str(run['run_id']),event,stage='committing-updates' if waiting else 'updates-committed')
  if failed:
   message='; '.join(str(item.get('error') or 'game update commit failed') for item in failed)[:1000];event=update_maintenance_event(event,work_error=message);self.repository.update_event(str(run['run_id']),event,stage='commit-failed');result['game_failed']+=len(failed);return event,True
  return event,not waiting
 def _has_rollbackable_game(self,event:dict)->bool:
  return any(item.get('kind')=='game-update' and item.get('transaction_id') and item.get('status') not in {'committed','rolled_back','aligned'} for item in event.get('pending_work') or [] if isinstance(item,dict))
 def _recover_game(self,run:dict,event:dict,now:datetime,result:dict,reason:str)->None:
  rid=str(run['run_id']);recovery=dict(event.get('recovery') or {});phase=str(recovery.get('phase') or 'stop');recovery.setdefault('reason',reason)
  if phase=='stop':
   cid=str(recovery.get('stop_command_id') or '')
   if not cid:
    try:command=self._raw_lifecycle(run,'stop')
    except InstanceLifecycleCommandConflict:return
    recovery['stop_command_id']=str(command['command_id']);event['recovery']=recovery;self.repository.update_event(rid,event,stage='rollback-stopping');return
   command=self._command(cid);status=str((command or {}).get('status') or '')
   if status in {'queued','delivered'}:return
   if status!='completed':self.repository.finish(rid,success=False,error_code='rollback_stop_failed',error_detail=(command or {}).get('last_error') or reason,now=now);result['failed']+=1;return
   recovery['phase']='rollback';event['recovery']=recovery;self.repository.update_event(rid,event,stage='rolling-back');return
  if phase=='rollback':
   works=[dict(item) for item in event.get('pending_work') or [] if isinstance(item,dict)];waiting=False;failures=[]
   for index,item in enumerate(works):
    if item.get('kind')!='game-update' or not item.get('transaction_id') or item.get('status') in {'committed','rolled_back','aligned'}:continue
    updated,ready=self.game.rollback(str(run['instance_id']),item);works[index]=updated
    if updated.get('status')=='failed':failures.append(updated)
    if not ready:waiting=True
   event=update_maintenance_event(event,pending_work=works);event['recovery']=recovery;self.repository.update_event(rid,event,stage='rolling-back')
   if failures:self.repository.finish(rid,success=False,error_code='rollback_failed',error_detail='; '.join(str(item.get('error') or '') for item in failures)[:2000],now=now);result['failed']+=1;return
   if waiting:return
   recovery['phase']='start';event['recovery']=recovery;self.repository.update_event(rid,event,stage='rollback-starting');result['game_rolled_back']+=1;return
  if phase=='start':
   cid=str(recovery.get('start_command_id') or '')
   if not cid:
    try:command=self._raw_lifecycle(run,'start')
    except InstanceLifecycleCommandConflict:return
    recovery['start_command_id']=str(command['command_id']);event['recovery']=recovery;self.repository.update_event(rid,event,stage='rollback-starting');return
   command=self._command(cid);status=str((command or {}).get('status') or '')
   if status in {'queued','delivered'}:return
   if status!='completed':self.repository.finish(rid,success=False,error_code='rollback_recovery_start_failed',error_detail=(command or {}).get('last_error') or reason,now=now);result['failed']+=1;return
   recovery['phase']='doctor';event['recovery']=recovery;self.repository.update_event(rid,event,stage='rollback-validating');return
  cid=str(recovery.get('readiness_command_id') or '')
  if not cid:
   command=self._raw_lifecycle(run,'doctor');recovery['readiness_command_id']=str(command['command_id']);event['recovery']=recovery;self.repository.update_event(rid,event,stage='rollback-validating');return
  command=self._command(cid);status=str((command or {}).get('status') or '')
  if status in {'queued','delivered'}:return
  recovered=status=='completed' and _doctor_ready(command or {});detail=reason if recovered else reason+'; rollback recovery readiness failed';self.repository.finish(rid,success=False,error_code='readiness_failed_rolled_back' if recovered else 'rollback_recovery_failed',error_detail=detail,now=now);result['failed']+=1
 def _advance(self,run:dict,now:datetime,result:dict)->None:
  iid=str(run['instance_id']);rid=str(run['run_id']);policy=self.repository.policy(iid);run=self._ensure_event(run,policy);event=run.get('event') or {};due=_dt(run['due_at'])
  if isinstance(event.get('recovery'),dict):self._recover_game(run,event,now,result,str(event['recovery'].get('reason') or 'maintenance recovery'));return
  if now<due:
   if not event.get('warnings_enabled'):return
   sent={int(value) for value in (run.get('warnings_sent') or [])}
   for offset in due_warning_offsets(policy,due,now=now,sent_offsets=sent):
    try:self._warning(run,policy,offset);result['warnings']+=1;sent.add(offset)
    except Exception as exc:result['warning_failures'].append({'run_id':rid,'offset_seconds':offset,'error':str(exc)[:500]})
   return
  if not run.get('preflight_command_id'):
   run=self._refresh_event_work(run,policy);event=run.get('event') or event
   try:self._enqueue(run,'status',self.repository.mark_preflight);result['preflights']+=1
   except Exception as exc:self.repository.finish(rid,success=False,error_code='preflight_enqueue_failed',error_detail=str(exc),now=now);result['failed']+=1
   return
  preflight=self._command(run.get('preflight_command_id'));status=str((preflight or {}).get('status') or '')
  if status in {'queued','delivered'}:return
  if status!='completed':self._failed(run,'preflight_failed',preflight or {},now,result);return
  observed=_observed_state(preflight or {})
  capabilities=event.get('capabilities') if isinstance(event.get('capabilities'),dict) else {}
  native_current=self._native_command_for_current_due(run,event)
  native_status=str((native_current or {}).get('status') or '').lower()
  if native_status=='failed':
   self.repository.finish(
    rid,
    success=False,
    error_code='native_restart_prepare_failed',
    error_detail=str((native_current or {}).get('last_error') or 'DayZ native restart preparation failed'),
    now=now,
   );result['failed']+=1;return
  native_armed=bool(native_status=='completed' and capabilities.get('native_countdown'))
  if observed!='running':
   if not (native_armed and observed=='stopped'):
    self.repository.finish(rid,success=True,now=now);result['completed']+=1;result['skipped']+=1;return
  if capabilities.get('save'):
   if not run.get('save_command_id'):
    try:self._enqueue(run,'save',self.repository.mark_save);result['saves']+=1
    except InstanceLifecycleCommandConflict:return
    except Exception as exc:self.repository.finish(rid,success=False,error_code='save_enqueue_failed',error_detail=str(exc),now=now);result['failed']+=1
    return
   save=self._command(run.get('save_command_id'));save_status=str((save or {}).get('status') or '')
   if save_status in {'queued','delivered'}:return
   if save_status!='completed':self._failed(run,'save_failed',save or {},now,result);return
  if native_armed:
   if observed=='running':
    event,native_stopped=self._wait_native_shutdown(run,event,now,result)
    if not native_stopped:return
  else:
   if not run.get('stop_command_id'):
    try:self._enqueue(run,'stop',self.repository.mark_stop);result['stops']+=1
    except InstanceLifecycleCommandConflict:return
    except Exception as exc:self.repository.finish(rid,success=False,error_code='stop_enqueue_failed',error_detail=str(exc),now=now);result['failed']+=1
    return
   stop=self._command(run.get('stop_command_id'));stop_status=str((stop or {}).get('status') or '')
   if stop_status in {'queued','delivered'}:return
   if stop_status!='completed':self._failed(run,'stop_failed',stop or {},now,result);return
  event=dict(self.repository.run(rid).get('event') or event)
  if event.get('coalesce_updates'):
   event,ready=self._apply_game_work(run,event,result)
   if not ready:return
   event,ready=self._apply_content_work(run,event,result)
   if not ready:return
  if capabilities.get('native_countdown'):
   event,native_ready=self._prepare_next_native_restart(run,event,now,result)
   if not native_ready:return
   if event.get('work_error'):
    self.repository.finish(rid,success=False,error_code='native_restart_prepare_failed',error_detail=str(event.get('work_error')),now=now);result['failed']+=1;return
  if not run.get('start_command_id'):
   try:self._enqueue(run,'start',self.repository.mark_start);result['starts']+=1
   except InstanceLifecycleCommandConflict:return
   except Exception as exc:self.repository.finish(rid,success=False,error_code='start_enqueue_failed',error_detail=str(exc),now=now);result['failed']+=1
   return
  start=self._command(run.get('start_command_id'));start_status=str((start or {}).get('status') or '')
  if start_status in {'queued','delivered'}:return
  if start_status!='completed':
   if self._has_rollbackable_game(event):event['recovery']={'phase':'stop','reason':str(start.get('last_error') or 'start failed after game update')};self.repository.update_event(rid,event,stage='rollback-stopping');return
   self._failed(run,'start_failed',start or {},now,result);return
  if not run.get('readiness_command_id'):
   try:self._enqueue(run,'doctor',self.repository.mark_readiness)
   except Exception as exc:self.repository.finish(rid,success=False,error_code='readiness_enqueue_failed',error_detail=str(exc),now=now);result['failed']+=1
   return
  doctor=self._command(run.get('readiness_command_id'));doctor_status=str((doctor or {}).get('status') or '')
  if doctor_status in {'queued','delivered'}:return
  if doctor_status=='completed' and _doctor_ready(doctor or {}):
   event,committed=self._finalize_game_work(run,event,result)
   if not committed:return
   if self._has_rollbackable_game(event):event['recovery']={'phase':'stop','reason':str(event.get('work_error') or 'game update commit failed')};self.repository.update_event(rid,event,stage='rollback-stopping');return
   latest=self.repository.run(rid);latest_event=latest.get('event') or {};error=str(latest_event.get('work_error') or '').strip();native_state=latest_event.get('native_restart') if isinstance(latest_event.get('native_restart'),dict) else {};next_due_override=native_state.get('due_at') if not error and native_state.get('status')=='completed' else None;self.repository.finish(rid,success=not bool(error),error_code='maintenance_work_failed' if error else None,error_detail=error or None,now=now,next_due_override=next_due_override);result['failed' if error else 'completed']+=1
  else:
   reason=(doctor or {}).get('last_error') or 'instance is not ready after maintenance'
   if self._has_rollbackable_game(event):event['recovery']={'phase':'stop','reason':str(reason)};self.repository.update_event(rid,event,stage='rollback-stopping');return
   self.repository.finish(rid,success=False,error_code='readiness_failed',error_detail=reason,now=now);result['failed']+=1
 def tick(self,*,now:datetime|None=None)->dict:
  current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc);result={'planned':0,'active':0,'warnings':0,'preflights':0,'saves':0,'stops':0,'starts':0,'native_restart_prepared':0,'native_shutdown_checks':0,'native_shutdowns':0,'native_shutdown_timeouts':0,'game_activated':0,'game_waiting':0,'game_committed':0,'game_rolled_back':0,'game_failed':0,'content_dispatched':0,'content_aligned':0,'content_waiting':0,'content_failed':0,'completed':0,'skipped':0,'failed':0,'warning_failures':[]}
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
   if result['active'] or result['failed']:print(f"maintenance worker active={result['active']} planned={result['planned']} warnings={result['warnings']} saves={result['saves']} stops={result['stops']} game={result['game_activated']}/{result['game_committed']} content={result['content_dispatched']}/{result['content_aligned']} starts={result['starts']} completed={result['completed']} skipped={result['skipped']} failed={result['failed']}",flush=True)
  except Exception as exc:print(f'maintenance worker failed: {exc}',file=sys.stderr,flush=True)
  time.sleep(max(1,int(interval)))
if __name__=='__main__':run_forever()
