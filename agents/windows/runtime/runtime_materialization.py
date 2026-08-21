"""Game-agnostic runtime materialization and reconciliation for Windows Agents."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import instance_runtime
from adapters import resolve_adapter
from runtime_events import emit_runtime_event
from runtime_spec import validate_runtime_spec
def _events():return Path(instance_runtime.STATE_DIR)
def _validate_materialization(spec:dict[str,Any])->dict[str,Any]:
 if spec["adapter"]=="windows-process":
  exe=Path(spec["executable"]);cwd=Path(spec["working_directory"])
  if not cwd.is_dir():raise RuntimeError("runtime working directory does not exist")
  if not exe.is_file():raise RuntimeError("runtime executable does not exist")
  try:exe.resolve(strict=False).relative_to(cwd.resolve(strict=False))
  except ValueError:raise RuntimeError("runtime executable escapes working directory")
  return {"materializer":"windows-process","exists":True,"owned":True,"matches":True,"executable":str(exe)}
 state=resolve_adapter(spec).status(spec)
 if not state.get("available"):raise RuntimeError("Windows service runtime is unavailable")
 return {"materializer":"windows-service","exists":True,"owned":True,"matches":True,"service":state.get("service")}
def materialize(config:dict[str,Any],spec:dict[str,Any])->dict[str,Any]:
 agent_id=str(config.get("agent_id") or "").strip();normalized=validate_runtime_spec(spec,expected_agent_id=agent_id);emit_runtime_event(_events(),"INSTANCE_RUNTIME_MATERIALIZING",agent_id=agent_id,instance_id=normalized["instance_id"])
 try:
  operation=_validate_materialization(normalized);record=instance_runtime.register_instance({**normalized,"observed_state":"unknown","materialized":True});event=emit_runtime_event(_events(),"INSTANCE_RUNTIME_READY",agent_id=agent_id,instance_id=normalized["instance_id"],data={"adapter":normalized["adapter"],"changed":True});return {"spec":normalized,"instance":record,"operation":{"action":"materialize","changed":True,"state":operation},"event":event}
 except Exception as exc:
  emit_runtime_event(_events(),"INSTANCE_RUNTIME_FAILED",agent_id=agent_id,instance_id=normalized["instance_id"],data={"phase":"materialize","error":str(exc)[:2000]});raise
def reconcile(config:dict[str,Any],instance_id:str)->dict[str,Any]:
 record=instance_runtime._owned(config,instance_id);normalized=validate_runtime_spec(record,expected_agent_id=str(config.get("agent_id") or ""));_validate_materialization(normalized);adapter=resolve_adapter(normalized);before=adapter.status(normalized);desired=normalized["desired_state"];running=bool(before.get("running") or before.get("active_state")=="active");operation=None
 if desired=="running" and not running:operation=adapter.start(normalized)
 elif desired=="stopped" and running:operation=adapter.stop(normalized)
 after=adapter.status(normalized);observed=instance_runtime._observed_state(after,record.get("observed_state"));updated=instance_runtime.register_instance({**record,"observed_state":observed});event=emit_runtime_event(_events(),"INSTANCE_RUNTIME_RECONCILED" if operation else "INSTANCE_RUNTIME_IN_SYNC",agent_id=normalized["agent_id"],instance_id=normalized["instance_id"],data={"desired_state":desired,"observed_state":observed,"changed":operation is not None});return {"instance_id":normalized["instance_id"],"desired_state":desired,"observed_state":observed,"changed":operation is not None,"operation":operation,"instance":updated,"event":event}
def remove(config:dict[str,Any],instance_id:str)->dict[str,Any]:
 record=instance_runtime._owned(config,instance_id);normalized=validate_runtime_spec(record,expected_agent_id=str(config.get("agent_id") or ""));adapter=resolve_adapter(normalized);state=adapter.status(normalized);stopped=None
 if bool(state.get("running") or state.get("active_state")=="active"):stopped=adapter.stop(normalized)
 try:instance_runtime._instance_path(instance_id).unlink()
 except FileNotFoundError:pass
 event=emit_runtime_event(_events(),"INSTANCE_RUNTIME_REMOVED",agent_id=normalized["agent_id"],instance_id=normalized["instance_id"],data={"changed":True});return {"instance_id":normalized["instance_id"],"stop":stopped,"operation":{"action":"remove","changed":True},"event":event}
__all__=["materialize","reconcile","remove"]
