"""Cross-platform distributed runtime services for the Windows Agent.

This module mirrors the Linux Agent command/state surfaces while keeping
Windows-specific lifecycle operations behind adapters.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import instance_runtime
from adapters import AdapterError, resolve_adapter

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", PROGRAM_DATA / "CapivaraAgent" / "state"))
EVENT_DIR = STATE_DIR / "runtime-events"
CONFIG_DIR = STATE_DIR / "managed-configuration"
CONTENT_DIR = STATE_DIR / "managed-content"
BACKUP_DIR = Path(os.environ.get("CAPIVARA_AGENT_BACKUP_DIR", STATE_DIR / "backups"))
BROADCAST_DIR = STATE_DIR / "broadcast-state"
PROVISION_DIR = STATE_DIR / "instance-provisioning"
METRICS_PATH = STATE_DIR / "runtime-metrics.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe(value: Any, label: str = "identifier") -> str:
    text = str(value or "").strip()
    if not text or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in text):
        raise ValueError(f"invalid {label}")
    return text


def _read(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".capivara-", suffix=".tmp", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


# Runtime events -----------------------------------------------------------
def emit_runtime_event(event_type: str, *, agent_id: str, instance_id: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "event_id": str(uuid.uuid4()), "event_type": str(event_type), "agent_id": agent_id,
        "instance_id": instance_id, "occurred_at": _now(), "data": dict(data or {}),
    }
    _write(EVENT_DIR / f"{event['event_id']}.json", event)
    increment("runtime_events_emitted")
    return event


def read_runtime_events(*, limit: int = 200) -> list[dict[str, Any]]:
    values = []
    if EVENT_DIR.is_dir():
        for path in sorted(EVENT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)[:max(1, min(limit, 1000))]:
            value = _read(path)
            if isinstance(value, dict): values.append(value)
    return values


def acknowledge_runtime_events(ids: list[Any]) -> None:
    for value in ids[:1000]:
        try: (EVENT_DIR / f"{_safe(value, 'event id')}.json").unlink()
        except FileNotFoundError: pass


# Metrics ------------------------------------------------------------------
def _metrics() -> dict[str, Any]:
    value = _read(METRICS_PATH, {})
    return value if isinstance(value, dict) else {}


def increment(name: str, amount: int = 1) -> None:
    name = _safe(name, "metric")
    value = _metrics(); counters = value.setdefault("counters", {})
    counters[name] = int(counters.get(name, 0)) + int(amount)
    value["updated_at"] = _now(); _write(METRICS_PATH, value)


def metrics_snapshot() -> dict[str, Any]:
    value = _metrics(); value.setdefault("counters", {}); value["reported_at"] = _now(); return value


# Configuration ------------------------------------------------------------
def configuration_state() -> list[dict[str, Any]]:
    value = _read(CONFIG_DIR / "state.json", {})
    reports = value.get("reports") if isinstance(value, dict) else []
    return [dict(x) for x in reports if isinstance(x, dict)]


def apply_configuration_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states = {(str(x.get("target_type")), str(x.get("target_id")), str(x.get("namespace"))): x for x in configuration_state()}
    for command in commands[:1000]:
        target_type = str(command.get("target_type") or "").lower(); target_id = _safe(command.get("target_id"), "target id")
        namespace = _safe(command.get("namespace"), "namespace")
        if target_type not in {"agent", "instance"}: raise ValueError("configuration target is invalid")
        value = command.get("value")
        if not isinstance(value, dict): raise ValueError("configuration value must be an object")
        revision = str(command.get("revision") or "").strip(); checksum = str(command.get("checksum") or "").strip()
        if not revision or not checksum: raise ValueError("configuration revision/checksum required")
        document = {"schema_version":1,"kind":"CapivaraAppliedConfiguration","target_type":target_type,"target_id":target_id,
                    "namespace":namespace,"revision":revision,"checksum":checksum,"value":value,"applied_at":_now(),
                    "configuration_refs":list(command.get("configuration_refs") or [])}
        _write(CONFIG_DIR / target_type / target_id / f"{namespace}.json", document)
        report = {"target_type":target_type,"target_id":target_id,"namespace":namespace,"desired_revision":revision,
                  "applied_revision":revision,"desired_checksum":checksum,"applied_checksum":checksum,"status":"applied",
                  "last_error":None,"reported_at":document["applied_at"],"configuration_refs":document["configuration_refs"]}
        states[(target_type,target_id,namespace)] = report
    reports = [states[key] for key in sorted(states)]
    _write(CONFIG_DIR / "state.json", {"schema_version":1,"reports":reports,"reported_at":_now()})
    return reports


# Managed content ----------------------------------------------------------
def content_state() -> list[dict[str, Any]]:
    value = _read(CONTENT_DIR / "state.json", {})
    reports = value.get("reports") if isinstance(value, dict) else []
    return [dict(x) for x in reports if isinstance(x, dict)]


def apply_content_commands(config: dict[str, Any], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states = {(str(x.get("instance_id")), str(x.get("content_id"))): x for x in content_state()}
    for command in commands[:500]:
        instance_id = _safe(command.get("instance_id"), "instance id"); content_id = _safe(command.get("content_id") or command.get("id"), "content id")
        action = str(command.get("action") or "install").lower()
        if action not in {"install","update","remove","verify"}: raise ValueError("unsupported content action")
        record = instance_runtime.get_instance(instance_id)
        if not record or str(record.get("agent_id")) != str(config.get("agent_id")): raise PermissionError("instance is not owned by this Agent")
        root = Path(str(record.get("path") or ""))
        target = root / "content" / content_id
        status = "applied"; error = None
        try:
            if action == "remove":
                if target.is_dir(): shutil.rmtree(target)
                elif target.exists(): target.unlink()
            elif action == "verify":
                if not target.exists(): raise RuntimeError("managed content is not installed")
            else:
                target.mkdir(parents=True, exist_ok=True)
                _write(target / ".capivara-content.json", {"content_id":content_id,"action":action,"source":command.get("source"),"updated_at":_now()})
        except Exception as exc:
            status = "failed"; error = str(exc)[:2000]
        report = {"instance_id":instance_id,"content_id":content_id,"action":action,"status":status,"last_error":error,"reported_at":_now()}
        states[(instance_id,content_id)] = report
        emit_runtime_event("INSTANCE_CONTENT_RECONCILED" if status=="applied" else "INSTANCE_CONTENT_FAILED", agent_id=str(config.get("agent_id")), instance_id=instance_id, data=report)
    reports = [states[key] for key in sorted(states)]
    _write(CONTENT_DIR / "state.json", {"schema_version":1,"reports":reports,"reported_at":_now()})
    return reports


# Backups ------------------------------------------------------------------
def backup_state() -> list[dict[str, Any]]:
    value = _read(BACKUP_DIR / "state.json", {})
    reports = value.get("reports") if isinstance(value, dict) else []
    return [dict(x) for x in reports if isinstance(x, dict)]


def _backup_record(instance_id: str, backup_id: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"instance_id":instance_id,"backup_id":backup_id,"status":status,"reported_at":_now(),**extra}


def apply_backup_commands(config: dict[str, Any], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states = {(str(x.get("instance_id")),str(x.get("backup_id"))):x for x in backup_state()}
    for command in commands[:100]:
        instance_id = _safe(command.get("instance_id"), "instance id"); action = str(command.get("action") or "create").lower()
        backup_id = _safe(command.get("backup_id") or uuid.uuid4().hex, "backup id")
        record = instance_runtime.get_instance(instance_id)
        if not record or str(record.get("agent_id")) != str(config.get("agent_id")): raise PermissionError("instance is not owned by this Agent")
        source = Path(str(record.get("path") or "")); archive = BACKUP_DIR / instance_id / f"{backup_id}.zip"
        try:
            if action == "create":
                if not source.is_dir(): raise RuntimeError("instance path is unavailable")
                archive.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                    for path in source.rglob("*"):
                        if path.is_file(): zf.write(path, path.relative_to(source))
                report = _backup_record(instance_id,backup_id,"completed",action=action,path=str(archive),size_bytes=archive.stat().st_size)
            elif action == "restore":
                if not archive.is_file(): raise RuntimeError("backup not found")
                source.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(archive) as zf:
                    for member in zf.infolist():
                        target = (source / member.filename).resolve(); target.relative_to(source.resolve())
                    zf.extractall(source)
                report = _backup_record(instance_id,backup_id,"completed",action=action,path=str(archive))
            elif action == "delete":
                archive.unlink(missing_ok=True); report = _backup_record(instance_id,backup_id,"completed",action=action)
            else: raise ValueError("unsupported backup action")
        except Exception as exc:
            report = _backup_record(instance_id,backup_id,"failed",action=action,error=str(exc)[:2000])
        states[(instance_id,backup_id)] = report
        emit_runtime_event("BACKUP_COMPLETED" if report["status"]=="completed" else "BACKUP_FAILED", agent_id=str(config.get("agent_id")), instance_id=instance_id, data=report)
    reports = [states[key] for key in sorted(states)]
    _write(BACKUP_DIR / "state.json", {"schema_version":1,"reports":reports,"reported_at":_now()})
    return reports


# Broadcast ---------------------------------------------------------------
def broadcast_state() -> list[dict[str, Any]]:
    value = _read(BROADCAST_DIR / "state.json", {})
    reports = value.get("reports") if isinstance(value, dict) else []
    return [dict(x) for x in reports if isinstance(x, dict)]


def apply_broadcast_commands(config: dict[str, Any], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states = {(str(x.get("broadcast_id")),str(x.get("instance_id"))):x for x in broadcast_state()}
    for command in commands[:200]:
        broadcast_id = _safe(command.get("broadcast_id") or command.get("command_id"), "broadcast id")
        instance_id = _safe(command.get("instance_id"), "instance id"); message = str(command.get("message") or "").strip()
        if not message: raise ValueError("broadcast message is required")
        record = instance_runtime.get_instance(instance_id)
        if not record or str(record.get("agent_id")) != str(config.get("agent_id")): raise PermissionError("instance is not owned by this Agent")
        try:
            operation = resolve_adapter(record).broadcast(record,message,priority=str(command.get("priority") or "normal"))
            report = {"broadcast_id":broadcast_id,"instance_id":instance_id,"status":"completed","operation":operation,"reported_at":_now()}
        except Exception as exc:
            report = {"broadcast_id":broadcast_id,"instance_id":instance_id,"status":"failed","error":str(exc)[:2000],"reported_at":_now()}
        states[(broadcast_id,instance_id)] = report
    reports=[states[key] for key in sorted(states)]; _write(BROADCAST_DIR/"state.json",{"schema_version":1,"reports":reports,"reported_at":_now()}); return reports


# Health/reconciliation/recovery ------------------------------------------
def health_inventory(config: dict[str, Any]) -> list[dict[str, Any]]:
    values=[]
    for item in instance_runtime.inventory(config):
        iid=str(item.get("instance_id"));
        try:
            doc=instance_runtime.doctor(config,iid); values.append({"instance_id":iid,"status":doc.get("status"),"ready":doc.get("ready"),"findings":doc.get("findings",[])})
        except Exception as exc: values.append({"instance_id":iid,"status":"critical","ready":False,"error":str(exc)[:2000]})
    return values


def reconciliation_inventory(config: dict[str, Any]) -> list[dict[str, Any]]:
    values=[]
    for item in instance_runtime.inventory(config):
        iid=str(item.get("instance_id")); record=instance_runtime.get_instance(iid) or {}
        try:
            view=instance_runtime.status(config,iid); values.append({"instance_id":iid,"desired_state":record.get("desired_state"),"observed_state":view.get("observed_state"),"reported_at":_now()})
        except Exception as exc: values.append({"instance_id":iid,"desired_state":record.get("desired_state"),"observed_state":"unknown","error":str(exc)[:2000],"reported_at":_now()})
    return values


def reconcile_all(config: dict[str, Any]) -> list[dict[str, Any]]:
    reports=[]
    for item in instance_runtime.inventory(config):
        iid=str(item.get("instance_id")); record=instance_runtime.get_instance(iid) or {}; desired=str(record.get("desired_state") or "").lower()
        try:
            view=instance_runtime.status(config,iid); observed=str(view.get("observed_state") or "unknown").lower(); action=None
            if desired=="running" and observed in {"stopped","failed"}: action="start"
            elif desired=="stopped" and observed in {"running","starting"}: action="stop"
            if action: instance_runtime.lifecycle(config,iid,action); increment(f"reconcile_{action}")
            reports.append({"instance_id":iid,"desired_state":desired or None,"observed_state":observed,"action":action,"status":"completed"})
        except Exception as exc:
            reports.append({"instance_id":iid,"desired_state":desired or None,"status":"failed","error":str(exc)[:2000]})
    return reports


def recover_interrupted_operations(config: dict[str, Any]) -> list[dict[str, Any]]:
    recovered=[]
    if PROVISION_DIR.is_dir():
        for path in PROVISION_DIR.glob("*.result.json"):
            value=_read(path)
            if isinstance(value,dict) and str(value.get("status")).lower()=="running":
                value.update({"status":"failed","current_step":"recovery","progress":100,"error":"Agent restarted while operation was running","recovered_at":_now()}); _write(path,value); recovered.append(value)
    if recovered: increment("operations_interrupted",len(recovered))
    return recovered


# Provisioning -------------------------------------------------------------
def provisioning_result() -> dict[str, Any] | None:
    candidates=[]
    if PROVISION_DIR.is_dir():
        for path in PROVISION_DIR.glob("*.result.json"):
            value=_read(path)
            if isinstance(value,dict):
                try: stamp=path.stat().st_mtime
                except OSError: stamp=0
                candidates.append((stamp,value))
    return sorted(candidates,key=lambda x:x[0],reverse=True)[0][1] if candidates else None


def stage_provisioning_command(config: dict[str, Any], command: dict[str, Any]) -> bool:
    if not isinstance(command,dict): return False
    provisioning_id=_safe(command.get("provisioning_id"),"provisioning id"); instance_id=_safe(command.get("instance_id"),"instance id")
    result_path=PROVISION_DIR/f"{provisioning_id}.result.json"
    existing=_read(result_path)
    if isinstance(existing,dict) and str(existing.get("status")).lower() in {"running","completed","failed"}: return False
    PROVISION_DIR.mkdir(parents=True,exist_ok=True); _write(PROVISION_DIR/f"{provisioning_id}.request.json",command)
    _write(result_path,{"provisioning_id":provisioning_id,"instance_id":instance_id,"status":"running","current_step":"prepare_workspace","progress":10})
    try:
        if str(command.get("agent_id") or config.get("agent_id")) != str(config.get("agent_id")): raise PermissionError("provisioning belongs to another Agent")
        workspace=STATE_DIR/"instance-workspaces"/instance_id; workspace.mkdir(parents=True,exist_ok=True)
        instance=dict(command.get("instance") or {}); instance.update({"instance_id":instance_id,"agent_id":str(config.get("agent_id"))})
        runtime=command.get("runtime") if isinstance(command.get("runtime"),dict) else {}
        instance.setdefault("runtime_id",runtime.get("runtime_id") or f"CapivaraInstance-{instance_id}")
        instance.setdefault("adapter",runtime.get("adapter") or "windows-service")
        instance.setdefault("path",str(workspace)); instance.setdefault("desired_state",command.get("desired_state") or "stopped"); instance.setdefault("observed_state","stopped")
        instance_runtime.register_instance(instance)
        final={"provisioning_id":provisioning_id,"instance_id":instance_id,"status":"completed","current_step":"completed","progress":100,"desired_state":instance.get("desired_state"),"observed_state":instance.get("observed_state"),"workspace":{"root":str(workspace)},"runtime":{"adapter":instance.get("adapter"),"runtime_id":instance.get("runtime_id")}}
        _write(result_path,final); increment("provisioning_completed"); emit_runtime_event("INSTANCE_PROVISIONING_COMPLETED",agent_id=str(config.get("agent_id")),instance_id=instance_id,data={"provisioning_id":provisioning_id}); return True
    except Exception as exc:
        _write(result_path,{"provisioning_id":provisioning_id,"instance_id":instance_id,"status":"failed","current_step":"materialize","progress":100,"error":str(exc)[:2000]}); increment("provisioning_failed"); emit_runtime_event("INSTANCE_PROVISIONING_FAILED",agent_id=str(config.get("agent_id")),instance_id=instance_id,data={"provisioning_id":provisioning_id,"error":str(exc)[:2000]}); return True


def clear_provisioning_result(provisioning_id: str) -> None:
    safe=_safe(provisioning_id,"provisioning id")
    for suffix in ("request.json","result.json"):
        try:(PROVISION_DIR/f"{safe}.{suffix}").unlink()
        except FileNotFoundError:pass


__all__=["acknowledge_runtime_events","apply_backup_commands","apply_broadcast_commands","apply_configuration_commands","apply_content_commands","backup_state","broadcast_state","clear_provisioning_result","configuration_state","content_state","emit_runtime_event","health_inventory","increment","metrics_snapshot","provisioning_result","read_runtime_events","reconcile_all","reconciliation_inventory","recover_interrupted_operations","stage_provisioning_command"]
