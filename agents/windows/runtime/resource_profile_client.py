"""Apply Controller-approved Resource Profile changes to Windows instance specs."""
from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import instance_runtime
from runtime_reconciler import reconcile_instance
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));RESULTS=STATE/"resource-results";HISTORY=STATE/"resource-history"
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _safe(v):
 s=str(v or "").strip()
 if not s or len(s)>191 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in s):raise ValueError("invalid resource command id")
 return s
def _path(root,cid):return root/f"{_safe(cid)}.json"
def _read(path):
 try:v=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,ValueError):return None
 return v if isinstance(v,dict) else None
def _write(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(f".{path.name}.{os.getpid()}.tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(tmp,path)
def apply(config:dict[str,Any],command:dict[str,Any])->dict[str,Any]:
 cid=_safe(command.get("command_id"));previous=_read(_path(HISTORY,cid))
 if previous is not None:_write(_path(RESULTS,cid),previous);return previous
 iid=str(command.get("instance_id") or "").strip();profile=str(command.get("resource_profile_id") or "").strip();resources=command.get("resources") if isinstance(command.get("resources"),dict) else {}
 try:
  record=instance_runtime.get_instance(iid)
  if not isinstance(record,dict):raise LookupError("instance not found")
  if str(record.get("agent_id") or "")!=str(config.get("agent_id") or ""):raise PermissionError("instance belongs to another Agent")
  updated=dict(record);updated["resource_profile_id"]=profile
  for key in ("cpu_limit_cores","memory_limit_bytes","storage_limit_bytes","player_limit","pids_limit"):
   if resources.get(key) is not None:updated[key]=resources[key]
  if resources.get("cpu_cores") is not None:updated["cpu_limit_cores"]=float(resources["cpu_cores"])
  if resources.get("memory_mb") is not None:updated["memory_limit_bytes"]=int(resources["memory_mb"])*1024*1024
  if resources.get("storage_mb") is not None:updated["storage_limit_bytes"]=int(resources["storage_mb"])*1024*1024
  instance_runtime.register_instance(updated);reconciled=reconcile_instance(config,iid,force=True)
  if str(reconciled.get("status") or "") not in {"healthy","completed"}:raise RuntimeError(reconciled.get("error") or "resource reconciliation failed")
  result={"command_id":cid,"instance_id":iid,"status":"completed","result":{"resource_profile_id":profile,"resources":resources,"reconcile":reconciled},"generated_at":_now()}
 except Exception as exc:result={"command_id":cid,"instance_id":iid or None,"status":"failed","error":str(exc)[:2000],"generated_at":_now()}
 _write(_path(HISTORY,cid),result);_write(_path(RESULTS,cid),result);return result
def read_result():
 try:paths=sorted(RESULTS.glob("*.json"))
 except OSError:paths=[]
 for path in paths:
  value=_read(path)
  if value:return value
 return None
def clear_result(cid):
 try:_path(RESULTS,cid).unlink()
 except FileNotFoundError:pass
__all__=["apply","clear_result","read_result"]
