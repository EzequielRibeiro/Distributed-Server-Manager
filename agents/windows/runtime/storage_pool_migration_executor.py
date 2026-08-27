"""Execute Windows per-instance Storage Pool migration and source cleanup."""
from __future__ import annotations
import hashlib,json,os,shutil,sys,time
from pathlib import Path
from typing import Any
import instance_runtime,runtime_materialization
from runtime_events import emit_runtime_event
from runtime_operations import runtime_operation
from storage_pool_migration_state import safe_id,write_json
from storage_pools import resolve_storage_pool
_ALLOWED_STOPPED={"stopped","offline","unknown","unavailable"}
def _result(path:Path,command:dict[str,Any],*,status:str,step:str,progress:int,**extra):
 migration_id=str(command.get("migration_id") or command.get("cleanup_id") or "");payload={"migration_id":migration_id,"instance_id":command["instance_id"],"status":status,"current_step":step,"progress":progress,**extra};write_json(path,payload);return payload
def _event(config,command,event_type,*,step,progress,data=None):
 emit_runtime_event(Path(instance_runtime.STATE_DIR),event_type,instance_id=command["instance_id"],agent_id=str(config.get("agent_id") or ""),data={"migration_id":str(command.get("migration_id") or command.get("cleanup_id") or ""),"source_storage_pool_id":command.get("source_storage_pool_id"),"target_storage_pool_id":command.get("target_storage_pool_id"),"step":step,"progress":progress,**dict(data or {})})
def _tree(root:Path)->tuple[dict[str,str],int]:
 files={};total=0
 if not root.exists():return files,total
 for current,dirs,names in os.walk(root,followlinks=False):
  base=Path(current)
  for name in list(dirs)+list(names):
   if (base/name).is_symlink():raise RuntimeError("Storage Pool operation refuses symlink")
  for name in names:
   path=base/name;relative=str(path.relative_to(root)).replace("\\","/");digest=hashlib.sha256();size=0
   with path.open("rb") as stream:
    for chunk in iter(lambda:stream.read(1024*1024),b""):digest.update(chunk);size+=len(chunk)
   files[relative]=digest.hexdigest();total+=size
 return files,total
def _copy_verified(source:Path,target:Path,migration_id:str)->dict[str,Any]:
 if not source.is_dir():raise RuntimeError("source instance state root does not exist")
 if target.exists():raise RuntimeError("target instance state root already exists")
 staging=target.parent/f".capivara-migrate-{safe_id(migration_id)}"
 if staging.exists():shutil.rmtree(staging)
 target.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(source,staging,symlinks=False)
 source_files,source_bytes=_tree(source);target_files,target_bytes=_tree(staging)
 if source_files!=target_files or source_bytes!=target_bytes:shutil.rmtree(staging,ignore_errors=True);raise RuntimeError("Storage Pool migration verification mismatch")
 os.replace(staging,target);return {"verified_files":len(source_files),"verified_bytes":source_bytes,"atomic_commit":True,"source_preserved":True}
def _replace_prefix(value:Any,source:Path,target:Path)->Any:
 if isinstance(value,str):
  old=str(source);new=str(target);lower=value.lower();old_lower=old.lower()
  if lower==old_lower:return new
  if lower.startswith(old_lower+os.sep.lower()):return new+value[len(old):]
  return value
 if isinstance(value,list):return [_replace_prefix(x,source,target) for x in value]
 if isinstance(value,dict):return {k:_replace_prefix(v,source,target) for k,v in value.items()}
 return value
def validate_command(config:dict[str,Any],command:dict[str,Any])->dict[str,Any]:
 if not isinstance(command,dict):raise ValueError("storage pool operation command must be an object")
 normalized=dict(command);identifier=command.get("migration_id") or command.get("cleanup_id");normalized["migration_id"]=safe_id(identifier,"migration_id");normalized["instance_id"]=safe_id(command.get("instance_id"),"instance_id");normalized["source_storage_pool_id"]=safe_id(command.get("source_storage_pool_id"),"source_storage_pool_id");normalized["target_storage_pool_id"]=safe_id(command.get("target_storage_pool_id"),"target_storage_pool_id");normalized["action"]=str(command.get("action") or "migrate").strip().lower();expected=str(config.get("agent_id") or "").strip();claimed=str(command.get("agent_id") or expected).strip()
 if not expected or claimed!=expected:raise PermissionError("storage pool operation belongs to another Agent")
 if normalized["source_storage_pool_id"]==normalized["target_storage_pool_id"]:raise ValueError("source and target storage pools must differ")
 resolve_storage_pool(config,normalized["source_storage_pool_id"],require_enabled=False);resolve_storage_pool(config,normalized["target_storage_pool_id"],require_enabled=normalized["action"]!="cleanup-source");return normalized
def _roots(config,command,record):
 source_pool=resolve_storage_pool(config,command["source_storage_pool_id"],require_enabled=False);target_pool=resolve_storage_pool(config,command["target_storage_pool_id"],require_enabled=False);source=(Path(source_pool["root_path"])/command["instance_id"]).resolve(strict=False);target=(Path(target_pool["root_path"])/command["instance_id"]).resolve(strict=False);actual=Path(str(record.get("instance_state_root") or target)).resolve(strict=False);return source,target,actual
def _cleanup(config,command,result_path):
 started=time.monotonic();_result(result_path,command,status="running",step="validate",progress=10);_event(config,command,"INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_STARTED",step="validate",progress=10)
 try:
  with runtime_operation(config,command["instance_id"],"storage-pool-cleanup",lock_timeout_seconds=float(config.get("runtime_lock_timeout_seconds",5))):
   record=dict(instance_runtime._owned(config,command["instance_id"]));source,target,actual=_roots(config,command,record)
   if str(record.get("storage_pool_id") or "")!=command["target_storage_pool_id"]:raise RuntimeError("instance is not assigned to migration target Storage Pool")
   if actual!=target:raise RuntimeError("instance state root does not match migration target Storage Pool")
   if not source.exists():return _result(result_path,command,status="completed",step="already_absent",progress=100,already_absent=True,deleted_files=0,deleted_bytes=0)
   files,total=_tree(source);expected_files=command.get("verified_files");expected_bytes=command.get("verified_bytes")
   if expected_files is not None and int(expected_files)!=len(files):raise RuntimeError("source file count changed after migration")
   if expected_bytes is not None and int(expected_bytes)!=total:raise RuntimeError("source byte count changed after migration")
   _result(result_path,command,status="running",step="delete_source",progress=70);_event(config,command,"INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_PROGRESS",step="delete_source",progress=70,data={"files":len(files),"bytes":total});shutil.rmtree(source)
   final=_result(result_path,command,status="completed",step="completed",progress=100,deleted_files=len(files),deleted_bytes=total,source_removed=True,elapsed_ms=int((time.monotonic()-started)*1000));_event(config,command,"INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_COMPLETED",step="completed",progress=100,data={"deleted_files":len(files),"deleted_bytes":total});return final
 except Exception as exc:
  failed=_result(result_path,command,status="failed",step="failed",progress=100,error=str(exc)[:2000],elapsed_ms=int((time.monotonic()-started)*1000));_event(config,command,"INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_FAILED",step="failed",progress=100,data={"error":str(exc)[:2000]});return failed
def _migrate(config,command,result_path):
 started=time.monotonic();original=None;copied=None;_result(result_path,command,status="running",step="staged",progress=1);_event(config,command,"INSTANCE_STORAGE_POOL_MIGRATION_STARTED",step="staged",progress=1)
 try:
  with runtime_operation(config,command["instance_id"],"storage-pool-migrate",lock_timeout_seconds=float(config.get("runtime_lock_timeout_seconds",5))):
   original=dict(instance_runtime._owned(config,command["instance_id"]));current=str(original.get("storage_pool_id") or "")
   if current!=command["source_storage_pool_id"]:raise RuntimeError("instance storage pool changed before migration")
   observed=str(instance_runtime.status(config,command["instance_id"]).get("observed_state") or "unknown").lower()
   if observed not in _ALLOWED_STOPPED:raise RuntimeError(f"instance must be stopped before storage pool migration: {observed}")
   source,target,actual=_roots(config,command,original)
   if actual!=source:raise RuntimeError("instance state root does not match source Storage Pool")
   _result(result_path,command,status="running",step="copy_verify",progress=20);copied=_copy_verified(source,target,command["migration_id"]);_result(result_path,command,status="running",step="switch_runtime",progress=75,**copied)
   updated=_replace_prefix(original,source,target);updated["storage_pool_id"]=command["target_storage_pool_id"];updated["instance_state_root"]=str(target);runtime_materialization.materialize(config,updated);instance_runtime.register_instance({**updated,"observed_state":"unknown","materialized":True})
   final=_result(result_path,command,status="completed",step="completed",progress=100,source_preserved=True,target_committed=True,verified_files=copied["verified_files"],verified_bytes=copied["verified_bytes"],elapsed_ms=int((time.monotonic()-started)*1000));_event(config,command,"INSTANCE_STORAGE_POOL_MIGRATION_COMPLETED",step="completed",progress=100,data={"verified_files":copied["verified_files"],"verified_bytes":copied["verified_bytes"],"source_preserved":True});return final
 except Exception as exc:
  rollback_error=None
  if original is not None:
   try:runtime_materialization.materialize(config,original);instance_runtime.register_instance(original)
   except Exception as rollback:rollback_error=str(rollback)[:1000]
  failed=_result(result_path,command,status="failed",step="failed",progress=100,error=str(exc)[:2000],rollback_error=rollback_error,source_preserved=True,target_committed=bool(copied),elapsed_ms=int((time.monotonic()-started)*1000));_event(config,command,"INSTANCE_STORAGE_POOL_MIGRATION_FAILED",step="failed",progress=100,data={"error":str(exc)[:2000],"rollback_error":rollback_error});return failed
def execute(config:dict[str,Any],command:dict[str,Any],result_path:Path):
 command=validate_command(config,command);return _cleanup(config,command,result_path) if command["action"]=="cleanup-source" else _migrate(config,command,result_path)
def main()->int:
 if len(sys.argv)!=4:return 2
 config=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"));command=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"));result=execute(config,command,Path(sys.argv[3]));return 0 if result.get("status")=="completed" else 1
if __name__=="__main__":raise SystemExit(main())
