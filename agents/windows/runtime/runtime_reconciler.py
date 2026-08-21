"""Continuous desired/observed reconciliation and safe recovery for Windows runtimes."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from pathlib import Path
import time
from typing import Any
import instance_runtime,runtime_materialization
from adapters import resolve_adapter
from runtime_events import emit_runtime_event
from runtime_metrics import increment,observe_duration
from runtime_operations import runtime_operation
from runtime_spec import validate_runtime_spec
DEFAULT_FAILURE_THRESHOLD=3;DEFAULT_BASE_BACKOFF_SECONDS=15;DEFAULT_MAX_BACKOFF_SECONDS=300
def _now():return datetime.now(timezone.utc)
def _stamp(v=None):return (v or _now()).isoformat().replace("+00:00","Z")
def _parse(v):
 text=str(v or "").strip()
 if not text:return None
 try:return datetime.fromisoformat(text.replace("Z","+00:00"))
 except ValueError:return None
def _settings(config):
 threshold=max(1,int(config.get("reconcile_failure_threshold",DEFAULT_FAILURE_THRESHOLD)));base=max(1,int(config.get("reconcile_base_backoff_seconds",DEFAULT_BASE_BACKOFF_SECONDS)));maximum=max(base,int(config.get("reconcile_max_backoff_seconds",DEFAULT_MAX_BACKOFF_SECONDS)));return threshold,base,maximum
def _event(event_type,record,data=None):emit_runtime_event(Path(instance_runtime.STATE_DIR),event_type,instance_id=str(record["instance_id"]),agent_id=str(record["agent_id"]),data=dict(data or {}))
def _save(record,*,status,observed_state=None,drift=None,retry_count=0,next_retry_at=None,error=None,recovery_action=None):
 body=dict(record)
 if observed_state is not None:body["observed_state"]=observed_state
 body["reconcile_status"]=status;body["reconcile_retry_count"]=int(retry_count);body["reconcile_last_attempt_at"]=_stamp();body["reconcile_next_retry_at"]=next_retry_at;body["reconcile_last_error"]=error;body["reconcile_drift"]=drift;body["reconcile_last_action"]=recovery_action
 if status=="healthy":body["reconcile_last_success_at"]=_stamp()
 return instance_runtime.register_instance(body)
def _backoff(config,retry_count):
 _,base,maximum=_settings(config);return min(maximum,base*(2**max(0,retry_count-1)))
def _failure(config,record,exc,*,drift=None):
 retries=int(record.get("reconcile_retry_count") or 0)+1;threshold,_,_=_settings(config);delay=_backoff(config,retries);next_retry=_stamp(_now()+timedelta(seconds=delay));status="degraded" if retries>=threshold else "retry_wait";error=str(exc)[:2000];updated=_save(record,status=status,drift=drift,retry_count=retries,next_retry_at=next_retry,error=error);increment("reconcile_failed");increment("instance_degraded") if status=="degraded" else None;_event("INSTANCE_DEGRADED" if status=="degraded" else "INSTANCE_RECONCILE_FAILED",updated,{"retry_count":retries,"next_retry_at":next_retry,"error":error,"drift":drift});return {"instance_id":record["instance_id"],"status":status,"retry_count":retries,"next_retry_at":next_retry,"error":error,"drift":drift}
def _reconcile_locked(config,record,normalized):
 drift=None;recovered=False;action=None
 try:
  adapter=resolve_adapter(normalized);before=adapter.status(normalized);observed_before=instance_runtime._observed_state(before,record.get("observed_state"));desired=normalized["desired_state"]
  if desired=="running" and observed_before!="running":drift="process_not_running";action="start";recovered=True;increment("drift_detected");_event("INSTANCE_DRIFT_DETECTED",normalized,{"drift":drift,"observed_state":observed_before})
  elif desired=="stopped" and observed_before=="running":drift="unexpected_running";action="stop";recovered=True;increment("drift_detected");_event("INSTANCE_DRIFT_DETECTED",normalized,{"drift":drift,"observed_state":observed_before})
  result=runtime_materialization.reconcile(config,normalized["instance_id"]);observed=str(result.get("observed_state") or "unknown");converged=(desired=="running" and observed=="running") or (desired=="stopped" and observed=="stopped")
  if not converged:raise RuntimeError(f"runtime did not converge: desired={desired} observed={observed}")
  latest=instance_runtime._owned(config,normalized["instance_id"]);updated=_save(latest,status="healthy",observed_state=observed,drift=None,retry_count=0,next_retry_at=None,error=None,recovery_action=action);increment("instance_recovered") if recovered else None;increment("reconcile_completed");_event("INSTANCE_RECOVERED" if recovered else "INSTANCE_RECONCILE_COMPLETED",updated,{"desired_state":desired,"observed_state":observed,"action":action});return {"instance_id":normalized["instance_id"],"status":"healthy","desired_state":desired,"observed_state":observed,"recovered":recovered,"action":action,"retry_count":0}
 except Exception as exc:return _failure(config,instance_runtime.get_instance(normalized["instance_id"]) or record,exc,drift=drift)
def reconcile_instance(config:dict[str,Any],instance_id:str,*,force:bool=False)->dict[str,Any]:
 record=instance_runtime._owned(config,instance_id);normalized=validate_runtime_spec(record,expected_agent_id=str(config.get("agent_id") or ""));retry_at=_parse(record.get("reconcile_next_retry_at"))
 if not force and retry_at is not None and retry_at>_now():return {"instance_id":normalized["instance_id"],"status":str(record.get("reconcile_status") or "retry_wait"),"retry_count":int(record.get("reconcile_retry_count") or 0),"next_retry_at":_stamp(retry_at),"skipped":True}
 started=time.monotonic();_event("INSTANCE_RECONCILE_STARTED",normalized,{"desired_state":normalized["desired_state"]})
 try:
  with runtime_operation(config,normalized["instance_id"],"reconcile",lock_timeout_seconds=float(config.get("runtime_lock_timeout_seconds",5))):result=_reconcile_locked(config,record,normalized)
 except Exception as exc:result=_failure(config,instance_runtime.get_instance(normalized["instance_id"]) or record,exc,drift="operation_conflict")
 observe_duration("reconcile",int((time.monotonic()-started)*1000));return result
def reconcile_all(config:dict[str,Any],*,force:bool=False)->list[dict[str,Any]]:
 results=[]
 for item in instance_runtime.list_instances(config):
  iid=str(item.get("instance_id") or "")
  if not iid:continue
  try:results.append(reconcile_instance(config,iid,force=force))
  except Exception as exc:results.append({"instance_id":iid,"status":"failed","error":str(exc)[:2000]})
 return results
def reconciliation_inventory(config:dict[str,Any])->list[dict[str,Any]]:
 values=[]
 for item in instance_runtime.list_instances(config):
  iid=str(item.get("instance_id") or "");record=instance_runtime.get_instance(iid) if iid else None
  if record:values.append({"instance_id":iid,"desired_state":record.get("desired_state"),"observed_state":record.get("observed_state","unknown"),"reconcile_status":record.get("reconcile_status","unknown"),"retry_count":int(record.get("reconcile_retry_count") or 0),"last_attempt_at":record.get("reconcile_last_attempt_at"),"last_success_at":record.get("reconcile_last_success_at"),"next_retry_at":record.get("reconcile_next_retry_at"),"last_error":record.get("reconcile_last_error"),"drift":record.get("reconcile_drift")})
 return values
__all__=["reconcile_all","reconcile_instance","reconciliation_inventory"]
