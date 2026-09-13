"""Apply activation snapshots to Windows runtime specs with rollback/readiness."""
from __future__ import annotations
from typing import Any
import instance_runtime
import runtime_materialization
from content_activation_runtime import project_runtime_spec
class ContentActivationApplyError(RuntimeError):pass
def _ready(config:dict[str,Any],instance_id:str)->bool:return bool(instance_runtime.doctor(config,instance_id).get("ready"))
def apply_activation_snapshots(config:dict[str,Any],snapshots:list[dict[str,Any]])->list[dict[str,Any]]:
 results=[]
 for snapshot in snapshots:
  iid=str(snapshot.get("instance_id") or "").strip()
  if not iid:continue
  previous=instance_runtime._owned(config,iid);projected=project_runtime_spec(previous,snapshot);old_checksum=str(previous.get("content_activation_checksum") or "");new_checksum=str(projected.get("content_activation_checksum") or "")
  if old_checksum==new_checksum:results.append({"instance_id":iid,"changed":False,"checksum":new_checksum});continue
  was_running=instance_runtime.status(config,iid).get("observed_state")=="running"
  try:
   if was_running:instance_runtime.lifecycle(config,iid,"stop")
   instance_runtime.register_instance(projected);runtime_materialization.materialize(config,projected)
   if was_running:
    instance_runtime.lifecycle(config,iid,"start")
    if not _ready(config,iid):raise ContentActivationApplyError("content activation failed readiness validation")
   results.append({"instance_id":iid,"changed":True,"checksum":new_checksum,"restarted":was_running})
  except Exception as exc:
   try:
    if was_running:
     try:instance_runtime.lifecycle(config,iid,"stop")
     except Exception:pass
    instance_runtime.register_instance(previous);runtime_materialization.materialize(config,previous)
    if was_running:
     instance_runtime.lifecycle(config,iid,"start")
     if not _ready(config,iid):raise ContentActivationApplyError("content activation rollback failed readiness validation")
   except Exception as rollback_exc:raise ContentActivationApplyError(f"activation failed and rollback failed: {rollback_exc}") from exc
   raise ContentActivationApplyError(str(exc)) from exc
 return results
__all__=["ContentActivationApplyError","apply_activation_snapshots"]
