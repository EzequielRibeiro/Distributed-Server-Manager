"""Durable local producer queue for Universal Event Platform ingestion on Windows."""
from __future__ import annotations
import json,os,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Iterable
EVENT_RELATIVE_PATH=Path("events")/"instance-runtime.jsonl";LEGACY_EVENT_NAMESPACE=uuid.UUID("f24888b7-652e-4511-a4fa-32065a32e217")
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _event_path(state_dir):
 path=Path(state_dir)/EVENT_RELATIVE_PATH;path.parent.mkdir(parents=True,exist_ok=True);return path
def _event_id(value):
 current=str(value.get("event_id") or "").strip()
 if current:return current
 stable={"agent_id":value.get("agent_id"),"instance_id":value.get("instance_id"),"event_type":value.get("event_type") or value.get("type"),"occurred_at":value.get("occurred_at"),"data":value.get("data") or {}};return str(uuid.uuid5(LEGACY_EVENT_NAMESPACE,json.dumps(stable,sort_keys=True,separators=(",",":"),default=str)))
def emit_runtime_event(state_dir:Path,event_type:str,*,instance_id:str,agent_id:str,data:dict[str,Any]|None=None,severity:str="info",correlation_id:str|None=None)->dict[str,Any]:
 payload={"schema_version":1,"kind":"CapivaraRuntimeEvent","event_id":str(uuid.uuid4()),"event_type":str(event_type).upper(),"type":str(event_type).upper(),"producer":"instance-runtime","source":"agent.runtime","instance_id":str(instance_id),"agent_id":str(agent_id),"severity":str(severity).lower(),"occurred_at":_now(),"correlation_id":correlation_id,"data":dict(data or {})};path=_event_path(Path(state_dir));fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
 try:os.write(fd,(json.dumps(payload,separators=(",",":"),sort_keys=True)+"\n").encode("utf-8"));os.fsync(fd)
 finally:os.close(fd)
 return payload
def read_runtime_events(state_dir:Path,*,limit:int=200)->list[dict[str,Any]]:
 path=_event_path(Path(state_dir));bounded=max(1,min(int(limit),1000));result=[]
 try:lines=path.read_text(encoding="utf-8").splitlines()
 except OSError:return []
 for line in lines[:bounded]:
  try:v=json.loads(line)
  except json.JSONDecodeError:continue
  if isinstance(v,dict):v=dict(v);v["event_id"]=_event_id(v);v["event_type"]=v.get("event_type") or v.get("type");result.append(v)
 return result
def acknowledge_runtime_events(state_dir:Path,event_ids:Iterable[str])->int:
 accepted={str(v).strip() for v in event_ids if str(v).strip()}
 if not accepted:return 0
 path=_event_path(Path(state_dir));kept=[];removed=0
 try:lines=path.read_text(encoding="utf-8").splitlines()
 except OSError:return 0
 for line in lines:
  try:v=json.loads(line)
  except json.JSONDecodeError:kept.append(line);continue
  eid=_event_id(v) if isinstance(v,dict) else ""
  if eid and eid in accepted:removed+=1
  else:kept.append(line)
 fd,name=tempfile.mkstemp(prefix=".runtime-events-",dir=str(path.parent),text=True)
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as stream:
   if kept:stream.write("\n".join(kept)+"\n")
   stream.flush();os.fsync(stream.fileno())
  os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)
 return removed
__all__=["emit_runtime_event","read_runtime_events","acknowledge_runtime_events"]
