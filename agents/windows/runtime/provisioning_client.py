"""Stage and supervise Windows provisioning without blocking Agent heartbeat."""
from __future__ import annotations
import os,subprocess,sys
from pathlib import Path
from typing import Any
from provisioning_state import PROVISION_ROOT,archive,paths,read_json,write_json
EXECUTOR=os.path.join(os.path.dirname(__file__),"provisioning_executor.py")
def read_provisioning_result()->dict[str,Any]|None:
 if not PROVISION_ROOT.is_dir():return None
 values=[]
 for p in PROVISION_ROOT.glob("*.result.json"):
  v=read_json(p)
  if isinstance(v,dict):
   try:s=p.stat().st_mtime
   except OSError:s=0
   values.append((s,v))
 return sorted(values,key=lambda x:x[0],reverse=True)[0][1] if values else None
def stage_provisioning_command(command:dict[str,Any]|None,*,config_path:Path)->bool:
 if not isinstance(command,dict):return False
 pid=str(command.get("provisioning_id") or "").strip();iid=str(command.get("instance_id") or "").strip()
 if not pid or not iid:return False
 req,res,log=paths(pid);existing=read_json(res)
 if isinstance(existing,dict) and str(existing.get("status") or "").lower() in {"running","completed","failed"}:return False
 PROVISION_ROOT.mkdir(parents=True,exist_ok=True);write_json(req,command);write_json(res,{"provisioning_id":pid,"instance_id":iid,"status":"running","current_step":"staged","progress":1});handle=open(log,"ab",buffering=0)
 try:
  subprocess.Popen([sys.executable,EXECUTOR,str(config_path),str(req),str(res)],stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT,close_fds=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
 except Exception as exc:
  write_json(res,{"provisioning_id":pid,"instance_id":iid,"status":"failed","current_step":"stage","progress":100,"error":str(exc)[:2000]});raise
 finally:handle.close()
 return True
def clear_provisioning_result(pid:str)->None:
 try:req,res,_=paths(pid)
 except ValueError:return
 archive(pid)
 for p in (req,res):
  try:p.unlink()
  except FileNotFoundError:pass
__all__=["clear_provisioning_result","read_provisioning_result","stage_provisioning_command"]
