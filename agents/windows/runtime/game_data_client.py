"""Stage and supervise Windows Agent game-data jobs without blocking heartbeat."""
from __future__ import annotations
import os, subprocess, sys
from typing import Any
from game_data_state import JOB_ROOT, archive_job, job_paths, read_json, write_json
EXECUTOR=os.path.join(os.path.dirname(__file__),"game_data_executor.py")
def read_game_data_result()->dict[str,Any]|None:
 if not JOB_ROOT.is_dir():return None
 values=[]
 for p in JOB_ROOT.glob("*.result.json"):
  v=read_json(p)
  if isinstance(v,dict):
   try:s=p.stat().st_mtime
   except OSError:s=0
   values.append((s,v))
 return sorted(values,key=lambda x:x[0],reverse=True)[0][1] if values else None
def stage_game_data_command(command):
 if not isinstance(command,dict):return False
 job=str(command.get("job_id") or "").strip(); sel=command.get("selection")
 if not job or not isinstance(sel,dict):return False
 req,res,log=job_paths(job); existing=read_json(res)
 if isinstance(existing,dict) and str(existing.get("status") or "").lower() in {"running","completed","failed"}:return False
 JOB_ROOT.mkdir(parents=True,exist_ok=True); write_json(req,command); write_json(res,{"job_id":job,"status":"running","progress":0}); handle=open(log,"ab",buffering=0)
 try:
  subprocess.Popen([sys.executable,EXECUTOR,str(req),str(res)],stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT,close_fds=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
 finally:handle.close()
 return True
def clear_game_data_result(job_id):
 try:req,res,_=job_paths(job_id)
 except ValueError:return
 archive_job(job_id)
 for p in (req,res):
  try:p.unlink()
  except FileNotFoundError:pass
__all__=["clear_game_data_result","read_game_data_result","stage_game_data_command"]
