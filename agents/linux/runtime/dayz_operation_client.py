#!/usr/bin/env python3
"""Execute typed DayZ map and wipe operations on Linux Agent."""
from __future__ import annotations
import json,os,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
RUNTIME_DIR=Path(__file__).resolve().parent
COMMON_DIR=RUNTIME_DIR.parent.parent/"common"
for item in (RUNTIME_DIR,COMMON_DIR):
    if str(item) not in sys.path:sys.path.insert(0,str(item))
from dayz_management import apply_mission,discover_missions,mod_compatibility_preflight,prepare_mission_persistence,restore_mission_persistence,wipe
from content_activation_projection import activation_snapshot
from content_activation_runtime import project_runtime_spec
from instance_runtime import get_instance,lifecycle,status
import privileged_materialization
STATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR","/var/lib/capivara-agent"))
RESULT_DIR=STATE_DIR/"dayz-operation-results";HISTORY_DIR=STATE_DIR/"dayz-operation-history";TRACE_DIR=STATE_DIR/"dayz-operation-traces"
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
def _trace_path(oid):return TRACE_DIR/f"{_token(oid,'operation_id')}.jsonl"
def _path_meta(path):
    try:
        stat=path.stat()
        return {"exists":True,"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}
    except FileNotFoundError:return {"exists":False}
    except OSError as exc:return {"exists":False,"error":str(exc)[:500]}
def _trace_stage(oid,stage,record,mission=None):
    mission=str(mission or record.get("mission") or "").strip()
    root=Path(str(record.get("instance_state_root") or "")).resolve()
    storage=root/"mpmissions"/mission/"storage_1" if mission else root/"mpmissions"/"__unknown__"/"storage_1"
    payload={
        "generated_at":_now(),"stage":stage,"mission":mission,
        "dayz_content_enabled":record.get("dayz_content_enabled"),
        "storage_1":_path_meta(storage),
        "types_bin":_path_meta(storage/"data"/"types.bin"),
        "events_bin":_path_meta(storage/"data"/"events.bin"),
        "seed_directories":record.get("seed_directories") or [],
        "bind_paths":record.get("bind_paths") or [],
        "arguments":record.get("arguments") or [],
    }
    path=_trace_path(oid);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as handle:
        handle.write(json.dumps(payload,sort_keys=True)+"\n")
def _runtime_identity(view):
    adapter=view.get("adapter_state") if isinstance(view.get("adapter_state"),dict) else {}
    raw_pid=adapter.get("main_pid") if adapter.get("main_pid") is not None else adapter.get("pid")
    try:pid=int(raw_pid or 0)
    except (TypeError,ValueError):pid=0
    raw_restarts=adapter.get("restart_count")
    try:restarts=int(raw_restarts) if raw_restarts is not None else None
    except (TypeError,ValueError):restarts=None
    return (pid or None,restarts,str(adapter.get("result") or ""))

def _stabilize(config,iid):
    try:seconds=max(0,min(int(os.environ.get("CAPIVARA_DAYZ_SWITCH_STABILIZE_SECONDS","120")),300))
    except (TypeError,ValueError):seconds=120
    initial_pid=None;initial_restarts=None;last="unknown"
    if seconds<=0:
        view=status(config,iid);last=str(view.get("observed_state") or "unknown");pid,restarts,_=_runtime_identity(view)
        return {"seconds":0,"observed_state":last,"process_id":pid,"restart_count":restarts}
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        view=status(config,iid);last=str(view.get("observed_state") or "unknown");pid,restarts,result=_runtime_identity(view)
        if last not in {"running","starting"}:raise RuntimeError(f"DayZ runtime became {last} during map-switch stabilization")
        if result in {"oom-kill","signal","core-dump","exit-code","watchdog","timeout","resources"}:
            raise RuntimeError(f"DayZ runtime reported systemd result {result} during map-switch stabilization")
        if pid:
            if initial_pid is None:initial_pid=pid
            elif pid!=initial_pid:raise RuntimeError(f"DayZ runtime restarted during map-switch stabilization: pid {initial_pid} -> {pid}")
        if restarts is not None:
            if initial_restarts is None:initial_restarts=restarts
            elif restarts>initial_restarts:raise RuntimeError(f"DayZ runtime restart count increased during map-switch stabilization: {initial_restarts} -> {restarts}")
        time.sleep(min(5,max(.1,deadline-time.monotonic())))
    final=status(config,iid);last=str(final.get("observed_state") or "unknown");pid,restarts,result=_runtime_identity(final)
    if last!="running":raise RuntimeError(f"DayZ runtime did not stabilize after map switch: {last}")
    if result in {"oom-kill","signal","core-dump","exit-code","watchdog","timeout","resources"}:
        raise RuntimeError(f"DayZ runtime reported systemd result {result} after map-switch stabilization")
    if initial_pid is not None and pid is not None and pid!=initial_pid:
        raise RuntimeError(f"DayZ runtime restarted during map-switch stabilization: pid {initial_pid} -> {pid}")
    if initial_restarts is not None and restarts is not None and restarts>initial_restarts:
        raise RuntimeError(f"DayZ runtime restart count increased during map-switch stabilization: {initial_restarts} -> {restarts}")
    return {"seconds":seconds,"observed_state":last,"process_id":pid or initial_pid,"restart_count":restarts}

def _content_enabled(record):
    explicit=record.get("dayz_content_enabled")
    if isinstance(explicit,bool):return explicit
    return any(str(arg or "").lower().startswith(("-mod=","-servermod=")) for arg in record.get("arguments") or [])

def _activation_order(snapshot):
    entries=(snapshot or {}).get("entries") if isinstance(snapshot,dict) else []
    if not isinstance(entries,list):return []
    result=[]
    for item in entries:
        if not isinstance(item,dict) or str(item.get("game_id") or "").strip().lower()!="dayz":continue
        result.append({
            "content_id":str(item.get("content_id") or ""),
            "package_id":str(item.get("package_id") or ""),
            "activation_order":int(item.get("activation_order") or 0),
        })
    return result

def _repair_hybrid_file_access(iid):
    template=str(os.environ.get("CAPIVARA_HYBRID_FILES_ACCESS_UNIT_TEMPLATE") or "").strip()
    if not template:
        materializer=str(os.environ.get("CAPIVARA_MATERIALIZER_UNIT_TEMPLATE") or "")
        if "dsm-hybrid-agent-materialize@" not in materializer:return None
        template="dsm-hybrid-agent-files-access@{instance_id}.service"
    unit=template.format(instance_id=_token(iid,"instance_id"))
    completed=subprocess.run(["systemctl","start",unit,"--no-pager"],capture_output=True,text=True,check=False,timeout=60)
    if completed.returncode!=0:
        raise RuntimeError((completed.stderr or completed.stdout or "Hybrid file-access helper failed")[:1000])
    return unit

def _change_mission(config,record,iid,payload,operation_id=None):
    before_view=discover_missions(record);previous_mission=before_view["current"];target=str(payload.get("mission") or "").strip()
    target_item=next((item for item in before_view["missions"] if item.get("id")==target),None)
    if target_item is None or not target_item.get("can_activate"):
        raise FileNotFoundError(f"DayZ mission is not installed or available: {target}")
    content_mode=str(payload.get("content_mode") or "disable").strip().lower()
    if content_mode not in {"disable","keep"}:raise ValueError("invalid DayZ map content mode")
    persistence_mode=str(payload.get("persistence_mode") or "fresh").strip().lower()
    if persistence_mode not in {"fresh","keep"}:raise ValueError("invalid DayZ map persistence mode")
    snapshot=activation_snapshot(iid);preflight=mod_compatibility_preflight(snapshot,target)
    if content_mode=="keep" and preflight.get("blocking"):
        blocked=[str(item.get("content_id") or item.get("package_id") or "content") for item in preflight.get("items") or [] if item.get("status")=="incompatible"]
        raise RuntimeError("DayZ mod compatibility preflight blocked mission "+target+": "+", ".join(blocked[:10]))
    if target==previous_mission:
        return {"previous_mission":previous_mission,"mission":target,"restarted":False,"rollback":False,"changed":False,"map":target_item,"content_mode":content_mode,"mods_enabled":content_mode=="keep","persistence_mode":persistence_mode,"mod_preflight":preflight,"activation_order":_activation_order(snapshot)}
    before=status(config,iid);was_running=before.get("observed_state") in {"running","starting"};previous_content_enabled=_content_enabled(record)
    if operation_id:_trace_stage(operation_id,"before_stop",record,target)
    if was_running:lifecycle(config,iid,"stop")
    if operation_id:_trace_stage(operation_id,"after_stop",record,target)
    persistence=None
    try:
        persistence=prepare_mission_persistence(record,target,persistence_mode)
        if operation_id:_trace_stage(operation_id,"after_prepare_persistence",record,target)
        updated=apply_mission(record,target)
        if operation_id:_trace_stage(operation_id,"after_apply_mission",updated,target)
        updated["dayz_content_enabled"]=content_mode=="keep"
        updated=project_runtime_spec(updated,snapshot)
        if operation_id:_trace_stage(operation_id,"after_content_projection",updated,target)
        privileged_materialization.materialize(config,updated)
        if operation_id:_trace_stage(operation_id,"after_materialization",updated,target)
        stabilization=None
        if was_running:
            if operation_id:_trace_stage(operation_id,"before_start",updated,target)
            lifecycle(config,iid,"start")
            if operation_id:_trace_stage(operation_id,"after_start",updated,target)
            stabilization=_stabilize(config,iid)
        after_view=discover_missions(updated);active=next((item for item in after_view["missions"] if item.get("active")),None)
        if not active or active.get("id")!=target:raise RuntimeError(f"DayZ mission activation verification failed: {target}")
        return {"previous_mission":previous_mission,"mission":target,"restarted":was_running,"rollback":False,"changed":True,"map":active,"content_mode":content_mode,"mods_enabled":content_mode=="keep","persistence_mode":persistence_mode,"persistence":persistence,"mod_preflight":preflight,"activation_order":_activation_order(snapshot),"stabilization":stabilization}
    except Exception as exc:
        rollback_error=None
        if was_running:
            try:
                current=status(config,iid)
                if current.get("observed_state") in {"running","starting"}:lifecycle(config,iid,"stop")
            except Exception as stop_exc:rollback_error=f"stop before rollback failed: {stop_exc}"
        try:_repair_hybrid_file_access(iid)
        except Exception as access_exc:rollback_error=(rollback_error+"; " if rollback_error else "")+f"file-access repair failed: {access_exc}"
        if persistence is not None:
            try:restore_mission_persistence(persistence)
            except Exception as persistence_exc:rollback_error=(rollback_error+"; " if rollback_error else "")+f"persistence rollback failed: {persistence_exc}"
        if previous_mission and previous_mission!=target:
            try:
                rollback=apply_mission(record,previous_mission)
                rollback["dayz_content_enabled"]=previous_content_enabled
                rollback=project_runtime_spec(rollback,snapshot)
                privileged_materialization.materialize(config,rollback)
            except Exception as rollback_exc:rollback_error=(rollback_error+"; " if rollback_error else "")+str(rollback_exc)[:1000]
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
        elif action=="change_mission":result=_change_mission(config,record,iid,payload,operation_id=oid)
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
