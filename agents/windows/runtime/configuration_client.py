"""Agent-side durable application/reporting for Controller-managed configuration."""
from __future__ import annotations
import json,os,tempfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));ROOT=STATE_ROOT/"managed-configuration"
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _safe(v):return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(v))
def _path(c):return ROOT/_safe(c.get("target_type") or "agent")/_safe(c.get("target_id") or "unknown")/f"{_safe(c.get('namespace') or 'default')}.json"
def _write(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True);fd,name=tempfile.mkstemp(prefix=".config-",dir=str(path.parent),text=True)
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as s:json.dump(payload,s,indent=2,sort_keys=True);s.write("\n");s.flush();os.fsync(s.fileno())
  os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)
def configuration_state():
 try:v=json.loads((ROOT/"state.json").read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError):return []
 reports=v.get("reports") if isinstance(v,dict) else None;return [dict(x) for x in reports if isinstance(x,dict)] if isinstance(reports,list) else []
def apply_configuration(command):
 if not isinstance(command,dict):raise ValueError("configuration command must be an object")
 value=command.get("value");namespace=str(command.get("namespace") or "").strip().lower();checksum=str(command.get("checksum") or "").strip();revision=str(command.get("revision") or "").strip();target_type=str(command.get("target_type") or "").strip().lower();target_id=str(command.get("target_id") or "").strip()
 if not isinstance(value,dict):raise ValueError("configuration value must be an object")
 if target_type not in {"agent","instance"} or not target_id:raise ValueError("configuration target is invalid")
 if not namespace or not checksum or not revision:raise ValueError("configuration namespace/revision/checksum required")
 doc={"schema_version":1,"kind":"CapivaraAppliedConfiguration","namespace":namespace,"target_type":target_type,"target_id":target_id,"revision":revision,"checksum":checksum,"value":value,"applied_at":_now(),"configuration_refs":list(command.get("configuration_refs") or [])};_write(_path(command),doc)
 return {"target_type":target_type,"target_id":target_id,"namespace":namespace,"desired_revision":revision,"applied_revision":revision,"desired_checksum":checksum,"applied_checksum":checksum,"status":"applied","last_error":None,"reported_at":doc["applied_at"],"configuration_refs":doc["configuration_refs"]}
def apply_configuration_commands(commands):
 states={(str(x.get("target_type") or ""),str(x.get("target_id") or ""),str(x.get("namespace") or "")):x for x in configuration_state()};changed=False
 for command in commands[:1000]:report=apply_configuration(command);states[(report["target_type"],report["target_id"],report["namespace"])]=report;changed=True
 reports=[states[k] for k in sorted(states)]
 if changed:_write(ROOT/"state.json",{"schema_version":1,"reports":reports,"reported_at":_now()})
 return reports
__all__=["apply_configuration","apply_configuration_commands","configuration_state"]
