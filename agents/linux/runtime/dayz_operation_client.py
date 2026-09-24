#!/usr/bin/env python3
"""Execute typed DayZ map and wipe operations on Linux Agent."""
from __future__ import annotations
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
RUNTIME_DIR=Path(__file__).resolve().parent
COMMON_DIR=RUNTIME_DIR.parent.parent/"common"
for item in (RUNTIME_DIR,COMMON_DIR):
    if str(item) not in sys.path:sys.path.insert(0,str(item))
from dayz_management import apply_mission,discover_missions,mod_compatibility_preflight,wipe
from content_activation_projection import activation_snapshot
from content_activation_runtime import project_runtime_spec
from instance_runtime import get_instance,lifecycle,status
import privileged_materialization
STATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR","/var/lib/capivara-agent"))
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
def _change_mission(config,record,iid,payload):
    before_view=discover_missions(record);previous_mission=before_view["current"];target=str(payload.get("mission") or "").strip()
    target_item=next((item for item in before_view["missions"] if item.get("id")==target),None)
    if target_item is None or not target_item.get("can_activate"):
        raise FileNotFoundError(f"DayZ mission is not installed or available: {target}")
    content_mode=str(payload.get("content_mode") or "disable").strip().lower()
    if content_mode not in {"disable","keep"}:raise ValueError("invalid DayZ map content mode")
    snapshot=activation_snapshot(iid);preflight=mod_compatibility_preflight(snapshot,target)
    if content_mode=="keep" and preflight.get("blocking"):
        blocked=[str(item.get("content_id") or item.get("package_id") or "content") for item in preflight.get("items") or [] if item.get("status")=="incompatible"]
        raise RuntimeError("DayZ mod compatibility preflight blocked mission "+target+": "+", ".join(blocked[:10]))
    if target==previous_mission:
        return {"previous_mission":previous_mission,"mission":target,"restarted":False,"rollback":False,"changed":False,"map":target_item,"content_mode":content_mode,"mods_enabled":content_mode=="keep","mod_preflight":preflight}
    before=status(config,iid);was_running=before.get("observed_state") in {"running","starting"}
    if was_running:lifecycle(config,iid,"stop")
    updated=None
    try:
        updated=apply_mission(record,target)
        updated["dayz_content_enabled"]=content_mode=="keep"
        updated=project_runtime_spec(updated,snapshot)
        privileged_materialization.materialize(config,updated)
        if was_running:lifecycle(config,iid,"start")
        after_view=discover_missions(updated);active=next((item for item in after_view["missions"] if item.get("active")),None)
        if not active or active.get("id")!=target:raise RuntimeError(f"DayZ mission activation verification failed: {target}")
        return {"previous_mission":previous_mission,"mission":target,"restarted":was_running,"rollback":False,"changed":True,"map":active,"content_mode":content_mode,"mods_enabled":content_mode=="keep","mod_preflight":preflight}
    except Exception as exc:
        rollback_error=None
        if previous_mission and previous_mission!=target:
            try:
                rollback=apply_mission(record,previous_mission)
                privileged_materialization.materialize(config,rollback)
            except Exception as rollback_exc:rollback_error=str(rollback_exc)[:1000]
        if was_running:
            try:lifecycle(config,iid,"start")
            except Exception as start_exc:
                rollback_error=(rollback_error+"; " if rollback_error else "")+f"restart after rollback failed: {start_exc}"
        detail=f"mission change failed and was rolled back: {exc}" if rollback_error is None else f"mission change failed: {exc}; rollback error: {rollback_error}"
        raise RuntimeError(detail) from exc
def handle_command(config:dict[str,Any],command:dict[str,Any])->dict[str,Any]:
    oid=_token(command.get("operation_id"),"operation_id");previous=_read(_history(oid))
    if previous is not None:_write(_result(oid),previous);return previous
    iid=str(command.get("instance_id") or "").strip();action=str(command.get("action") or "").strip().lower();payload=command.get("payload") if isinstance(command.get("payload"),dict) else {}
    partial=None
    try:
        iid=_token(iid,"instance_id");record=get_instance(iid)
        if record is None:raise LookupError(f"instance not found: {iid}")
        if str(record.get("agent_id") or "")!=str(config.get("agent_id") or ""):raise PermissionError("instance belongs to another Agent")
        if str(record.get("game_id") or "").lower()!="dayz":raise ValueError("DayZ operation requires DayZ instance")
        if action=="discover_missions":result=discover_missions(record)
        elif action=="change_mission":result=_change_mission(config,record,iid,payload)
        elif action=="wipe":
            before=status(config,iid);was_running=before.get("observed_state") in {"running","starting"}
            if was_running:lifecycle(config,iid,"stop")
            partial=wipe(record,payload.get("scope") or "persistence",bool(payload.get("backup",True)))
            if was_running:lifecycle(config,iid,"start")
            result={**partial,"restarted":was_running}
        else:raise ValueError("unsupported DayZ operation")
        response={"operation_id":oid,"instance_id":iid,"action":action,"status":"completed","result":result,"generated_at":_now()}
    except Exception as exc:
        response={"operation_id":oid,"instance_id":iid or None,"action":action or None,"status":"failed","error":str(exc)[:2000],"generated_at":_now()}
        if isinstance(partial,dict):response["result"]={**partial,"restarted":False}
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
