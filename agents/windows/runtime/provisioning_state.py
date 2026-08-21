"""Durable provisioning state for Windows Agents."""
from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));PROVISION_ROOT=STATE_ROOT/"instance-provisioning";HISTORY_ROOT=PROVISION_ROOT/"history"
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _safe(v):
 t=str(v or "").strip();allowed="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
 if not t or any(c not in allowed for c in t):raise ValueError("invalid provisioning id")
 return t
def read_json(path):
 try:v=json.loads(Path(path).read_text(encoding="utf-8"))
 except (OSError,ValueError):return None
 return v if isinstance(v,dict) else None
def write_json(path,payload):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+".tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(tmp,p)
def paths(pid):
 s=_safe(pid);return PROVISION_ROOT/f"{s}.request.json",PROVISION_ROOT/f"{s}.result.json",PROVISION_ROOT/f"{s}.log"
def archive(pid):
 req,res,log=paths(pid);r=read_json(req) or {};out=read_json(res) or {}
 if str(out.get("status") or "").lower() not in {"completed","failed"}:return None
 summary={"provisioning_id":pid,"instance_id":out.get("instance_id") or r.get("instance_id"),"status":out.get("status"),"current_step":out.get("current_step"),"progress":out.get("progress"),"error":out.get("error"),"archived_at":_now(),"log_path":str(log)};write_json(HISTORY_ROOT/f"{_safe(pid)}.json",{k:v for k,v in summary.items() if v is not None});return summary
__all__=["PROVISION_ROOT","archive","paths","read_json","write_json"]
