"""Stage and supervise Windows Storage Pool migration/cleanup jobs."""
from __future__ import annotations
import os,subprocess,sys
from pathlib import Path
from typing import Any
from storage_pool_migration_state import MIGRATION_ROOT,archive,paths,read_json,write_json
EXECUTOR=os.path.join(os.path.dirname(__file__),"storage_pool_migration_executor.py")
def read_storage_pool_migration_result()->dict[str,Any]|None:
 if not MIGRATION_ROOT.is_dir():return None
 values=[]
 for path in MIGRATION_ROOT.glob("*.result.json"):
  value=read_json(path)
  if isinstance(value,dict):
   try:stamp=path.stat().st_mtime
   except OSError:stamp=0
   values.append((stamp,value))
 return sorted(values,key=lambda item:item[0],reverse=True)[0][1] if values else None
def stage_storage_pool_migration(command:dict[str,Any]|None,*,config_path:Path)->bool:
 if not isinstance(command,dict):return False
 command=dict(command)
 if str(command.get("action") or "").strip().lower()=="cleanup-source":
  command.setdefault("verified_files",command.get("expected_verified_files"));command.setdefault("verified_bytes",command.get("expected_verified_bytes"))
 migration_id=str(command.get("migration_id") or command.get("cleanup_id") or "").strip();instance_id=str(command.get("instance_id") or "").strip()
 if not migration_id or not instance_id:return False
 request_path,result_path,log_path=paths(migration_id);existing=read_json(result_path)
 if isinstance(existing,dict) and str(existing.get("status") or "").lower() in {"running","completed","failed"}:return False
 MIGRATION_ROOT.mkdir(parents=True,exist_ok=True);write_json(request_path,command);write_json(result_path,{"migration_id":migration_id,"instance_id":instance_id,"status":"running","current_step":"staged","progress":1});handle=open(log_path,"ab",buffering=0)
 try:subprocess.Popen([sys.executable,EXECUTOR,str(config_path),str(request_path),str(result_path)],stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT,close_fds=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
 except Exception as exc:write_json(result_path,{"migration_id":migration_id,"instance_id":instance_id,"status":"failed","current_step":"stage","progress":100,"error":str(exc)[:2000]});raise
 finally:handle.close()
 return True
def clear_storage_pool_migration_result(migration_id:str)->None:
 try:req,res,_=paths(migration_id)
 except ValueError:return
 archive(migration_id)
 for path in (req,res):
  try:path.unlink()
  except FileNotFoundError:pass
__all__=["clear_storage_pool_migration_result","read_storage_pool_migration_result","stage_storage_pool_migration"]
