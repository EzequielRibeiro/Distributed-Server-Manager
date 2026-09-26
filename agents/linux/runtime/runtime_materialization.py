#!/usr/bin/env python3
"""Game-agnostic materialization and desired/observed reconciliation for Agent instances."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import instance_runtime
from adapters import resolve_adapter
from content_activation_projection import activation_snapshot
from content_activation_runtime import materialize_content_activation,project_runtime_spec
from materializers import resolve_materializer
from runtime_events import emit_runtime_event
from runtime_spec import validate_runtime_spec

def _state_dir()->Path:return Path(instance_runtime.STATE_DIR)
def _project(spec:dict[str,Any])->dict[str,Any]:
 iid=str(spec.get("instance_id") or "").strip()
 return project_runtime_spec(spec,activation_snapshot(iid)) if iid else dict(spec)

def materialize(config:dict[str,Any],spec:dict[str,Any])->dict[str,Any]:
 agent_id=str(config.get("agent_id") or "").strip();projected=_project(spec);normalized=validate_runtime_spec(projected,expected_agent_id=agent_id);emit_runtime_event(_state_dir(),"INSTANCE_RUNTIME_MATERIALIZING",instance_id=normalized["instance_id"],agent_id=agent_id);materializer=resolve_materializer(normalized)
 try:
  content_files=materialize_content_activation(normalized);operation=materializer.apply(normalized);record=instance_runtime.register_instance({**normalized,"observed_state":"unknown","materialized":True});event=emit_runtime_event(_state_dir(),"INSTANCE_RUNTIME_READY",instance_id=normalized["instance_id"],agent_id=agent_id,data={"adapter":normalized["adapter"],"changed":bool(operation.get("changed")),"content_files":content_files});return {"spec":normalized,"instance":record,"operation":operation,"content_files":content_files,"event":event}
 except Exception as exc:
  emit_runtime_event(_state_dir(),"INSTANCE_RUNTIME_FAILED",instance_id=normalized["instance_id"],agent_id=agent_id,data={"phase":"materialize","error":str(exc)[:2000]});raise

def reconcile(config:dict[str,Any],instance_id:str)->dict[str,Any]:
 from relocation_fence import locked
 if locked(instance_id):
  raise PermissionError("runtime reconciliation is disabled while relocation source is fenced")
 record=instance_runtime._owned(config,instance_id);projected=_project(record)
 if projected!=record:record=instance_runtime.register_instance(projected)
 normalized=validate_runtime_spec(record,expected_agent_id=str(config.get("agent_id") or ""));materializer=resolve_materializer(normalized);content_files=materialize_content_activation(normalized);materialized=materializer.inspect(normalized)
 if not materialized.get("exists") or not materialized.get("owned"):raise RuntimeError("instance runtime is not safely materialized")
 if not materialized.get("matches"):materializer.apply(normalized)
 adapter=resolve_adapter(normalized);before=adapter.status(normalized);desired=normalized["desired_state"];running=bool(before.get("running"));operation=None
 if desired=="running" and not running:operation=adapter.start(normalized)
 elif desired=="stopped" and running:operation=adapter.stop(normalized)
 after=adapter.status(normalized);observed=instance_runtime._observed_state(after,record.get("observed_state"));updated=instance_runtime.register_instance({**record,"observed_state":observed});event=emit_runtime_event(_state_dir(),"INSTANCE_RUNTIME_RECONCILED",instance_id=normalized["instance_id"],agent_id=normalized["agent_id"],data={"desired_state":desired,"observed_state":observed,"changed":True,"content_files":content_files}) if operation else None;return {"instance_id":normalized["instance_id"],"desired_state":desired,"observed_state":observed,"changed":operation is not None,"operation":operation,"content_files":content_files,"instance":updated,"event":event}

def remove(config:dict[str,Any],instance_id:str)->dict[str,Any]:
 record=instance_runtime._owned(config,instance_id);normalized=validate_runtime_spec(record,expected_agent_id=str(config.get("agent_id") or ""));adapter=resolve_adapter(normalized);state=adapter.status(normalized);stopped=None
 if bool(state.get("running")):stopped=adapter.stop(normalized)
 operation=resolve_materializer(normalized).remove(normalized)
 try:instance_runtime._instance_path(instance_id).unlink()
 except FileNotFoundError:pass
 event=emit_runtime_event(_state_dir(),"INSTANCE_RUNTIME_REMOVED",instance_id=normalized["instance_id"],agent_id=normalized["agent_id"],data={"changed":bool(operation.get("changed"))});return {"instance_id":normalized["instance_id"],"stop":stopped,"operation":operation,"event":event}
__all__=["materialize","reconcile","remove"]
