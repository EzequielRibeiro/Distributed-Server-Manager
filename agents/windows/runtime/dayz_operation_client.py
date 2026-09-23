#!/usr/bin/env python3
"""Execute typed DayZ map and wipe operations on Windows Agent."""
from __future__ import annotations
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
RUNTIME_DIR=Path(__file__).resolve().parent
COMMON_DIR=RUNTIME_DIR.parent.parent/"common"
for item in (RUNTIME_DIR,COMMON_DIR):
    if str(item) not in sys.path:sys.path.insert(0,str(item))
from dayz_management import apply_mission,discover_missions,wipe
from instance_runtime import get_instance,lifecycle,register_instance,status
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\\ProgramData"))\nSTATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"))
RESULT_DIR=STATE_DIR/"dayz-operation-results";HISTORY_DIR=STATE_DIR/"dayz-operation-history"
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _token(value,label):
    value=str(value or "").strip()
    if not value or len(value)>191 or not all(ch.isalnum() or ch in "._-" for ch in value):raise ValueError(f"invalid {label}")
    return value
def _read(path):
    try:value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):return None
    return value if isinstance(value,dict) else None
def _write(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:temp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.chmod(temp,0o600);os.replace(temp,path)
    finally:
        try:temp.unlink()
        except FileNotFoundError:pass
def _history(oid):return HISTORY_DIR/f"{_token(oid,'operation_id')}.json"
def _result(oid):return RESULT_DIR/f"{_token(oid,'operation_id')}.json"
def handle_command(config:dict[str,Any],command:dict[str,Any])->dict[str,Any]:
    oid=_token(command.get("operation_id"),"operation_id");previous=_read(_history(oid))
    if previous is not None:_write(_result(oid),previous);return previous
    iid=str(command.get("instance_id") or "").strip();action=str(command.get("action") or "").strip().lower();payload=command.get("payload") if isinstance(command.get("payload"),dict) else {}
    try:
        iid=_token(iid,"instance_id");record=get_instance(iid)
        if record is None:raise LookupError(f"instance not found: {iid}")
        if str(record.get("agent_id") or "")!=str(config.get("agent_id") or ""):raise PermissionError("instance belongs to another Agent")
        if str(record.get("game_id") or "").lower()!="dayz":raise ValueError("DayZ operation requires DayZ instance")
        if action=="discover_missions":result=discover_missions(record)
        elif action=="change_mission":
            before=status(config,iid);was_running=before.get("observed_state") in {"running","starting"}
            if was_running:lifecycle(config,iid,"stop")
            updated=apply_mission(record,payload.get("mission"));register_instance(updated)
            if was_running:lifecycle(config,iid,"start")
            result={"previous_mission":discover_missions(record)["current"],"mission":discover_missions(updated)["current"],"restarted":was_running}
        elif action=="wipe":
            before=status(config,iid);was_running=before.get("observed_state") in {"running","starting"}
            if was_running:lifecycle(config,iid,"stop")
            result=wipe(record,payload.get("scope") or "persistence",bool(payload.get("backup",True)))
            if was_running:lifecycle(config,iid,"start")
            result["restarted"]=was_running
        else:raise ValueError("unsupported DayZ operation")
        response={"operation_id":oid,"instance_id":iid,"action":action,"status":"completed","result":result,"generated_at":_now()}
    except Exception as exc:response={"operation_id":oid,"instance_id":iid or None,"action":action or None,"status":"failed","error":str(exc)[:2000],"generated_at":_now()}
    _write(_history(oid),response);_write(_result(oid),response);return response
def read_result():
    try:paths=sorted(RESULT_DIR.glob("*.json"))
    except OSError:paths=[]
    for path in paths:
        value=_read(path)
        if value:return value
    return None
def clear_result(operation_id):
    try:_result(operation_id).unlink()
    except FileNotFoundError:pass
__all__=["clear_result","handle_command","read_result"]
