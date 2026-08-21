"""Persistent game-data state for the Windows Agent."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))
STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"))
GAME_DATA_ROOT=Path(os.environ.get("CAPIVARA_AGENT_GAME_DATA_ROOT",STATE_ROOT/"game-data")).resolve()
JOB_ROOT=STATE_ROOT/"game-data-jobs"; HISTORY_ROOT=JOB_ROOT/"history"; GAME_STATE_ROOT=STATE_ROOT/"game-data-state"
def _now(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _safe(v,label):
 t=str(v or "").strip(); allowed="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
 if not t or any(c not in allowed for c in t): raise ValueError(f"invalid {label}")
 return t
def read_json(path):
 try:v=json.loads(Path(path).read_text(encoding="utf-8"))
 except (OSError,ValueError):return None
 return v if isinstance(v,dict) else None
def write_json(path,payload):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp"); tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(tmp,path)
def job_paths(job_id):
 s=_safe(job_id,"game-data job id"); return JOB_ROOT/f"{s}.request.json",JOB_ROOT/f"{s}.result.json",JOB_ROOT/f"{s}.log"
def archive_job(job_id):
 req,res,log=job_paths(job_id); r=read_json(req) or {}; out=read_json(res) or {}; status=str(out.get("status") or "").lower()
 if status not in {"completed","failed"}:return None
 sel=r.get("selection") if isinstance(r.get("selection"),dict) else {}; summary={"job_id":job_id,"action":r.get("action"),"environment_id":r.get("environment_id"),"selector":r.get("selector"),"status":status,"progress":out.get("progress"),"error":out.get("error"),"provider":out.get("provider") or sel.get("provider"),"game":out.get("game") or sel.get("game"),"version":out.get("version") or sel.get("version"),"target_path":out.get("target_path"),"log_path":str(log),"archived_at":_now()}; write_json(HISTORY_ROOT/f"{_safe(job_id,'game-data job id')}.json",{k:v for k,v in summary.items() if v is not None}); return summary
def record_game_data(*,job_id,action,selection,result):
 game=_safe(result.get("game") or selection.get("game"),"game id"); state={"game":game,"installed":True,"provider":result.get("provider") or selection.get("provider"),"version":result.get("version") or selection.get("version"),"target_path":result.get("target_path"),"last_action":action,"last_job_id":job_id,"updated_at":_now()}; write_json(GAME_STATE_ROOT/f"{game}.json",{k:v for k,v in state.items() if v is not None}); return state
def list_game_data():
 if not GAME_STATE_ROOT.is_dir():return []
 return [v for p in sorted(GAME_STATE_ROOT.glob("*.json")) if (v:=read_json(p))]
def summary():
 games=list_game_data(); active=0
 if JOB_ROOT.is_dir():
  for p in JOB_ROOT.glob("*.result.json"):
   v=read_json(p) or {}; active+=str(v.get("status")).lower() not in {"completed","failed"}
 return {"game_data_root":str(GAME_DATA_ROOT),"installed_count":len(games),"active_jobs":active}
__all__=["GAME_DATA_ROOT","JOB_ROOT","archive_job","job_paths","read_json","record_game_data","summary","write_json"]
