#!/usr/bin/env python3
"""Agent-side universal broadcast delivery and durable acknowledgements."""
from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from adapters import AdapterError,resolve_adapter
from instance_runtime import get_instance
STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR","/var/lib/capivara-agent"));STATE_DIR=STATE_ROOT/"broadcast-state"
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _write(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(f".{path.name}.{os.getpid()}.tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.chmod(tmp,0o600);os.replace(tmp,path)
def _path(delivery_id):
 safe="".join(c for c in str(delivery_id) if c.isalnum() or c in "._-")
 if not safe or safe!=str(delivery_id):raise ValueError("invalid delivery_id")
 return STATE_DIR/f"{safe}.json"
def apply_broadcast_commands(config:dict[str,Any],commands:list[dict[str,Any]])->list[dict[str,Any]]:
 reports=[];agent_id=str(config.get("agent_id") or "")
 for cmd in commands[:500]:
  delivery_id=str(cmd.get("delivery_id") or "");iid=str(cmd.get("instance_id") or "");path=_path(delivery_id)
  try:
   previous=json.loads(path.read_text()) if path.exists() else {}
  except Exception:previous={}
  if previous.get("status")=="acknowledged":reports.append(previous);continue
  try:
   if str(cmd.get("agent_id") or agent_id)!=agent_id:raise PermissionError("Agent identity mismatch")
   instance=get_instance(iid)
   if not instance:raise LookupError("instance not found")
   if str(instance.get("agent_id") or "")!=agent_id:raise PermissionError("instance belongs to another Agent")
   expires=str(cmd.get("expires_at") or "")
   if expires and expires<=_now():raise TimeoutError("broadcast expired")
   message=str(cmd.get("message") or "")
   if not message or len(message)>4000:raise ValueError("invalid broadcast message")
   adapter=resolve_adapter(instance);adapter.broadcast(instance,message,priority=str(cmd.get("priority") or "normal"))
   now=_now();report={"delivery_id":delivery_id,"broadcast_id":cmd.get("broadcast_id"),"instance_id":iid,"status":"acknowledged" if cmd.get("require_ack",True) else "delivered","delivered_at":now,"acknowledged_at":now if cmd.get("require_ack",True) else None,"last_error":None}
  except Exception as exc:
   report={"delivery_id":delivery_id,"broadcast_id":cmd.get("broadcast_id"),"instance_id":iid,"status":"failed","delivered_at":None,"acknowledged_at":None,"last_error":str(exc)[:2000]}
  _write(path,report);reports.append(report)
 return reports
def broadcast_state()->list[dict[str,Any]]:
 out=[]
 try:paths=sorted(STATE_DIR.glob("*.json"))
 except OSError:paths=[]
 for path in paths:
  try:v=json.loads(path.read_text(encoding="utf-8"))
  except Exception:continue
  if isinstance(v,dict):out.append(v)
 return out[:1000]
__all__=["apply_broadcast_commands","broadcast_state"]
