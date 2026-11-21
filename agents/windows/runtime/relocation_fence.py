"""Durable Windows Service source fencing during cross-Agent relocation."""
from __future__ import annotations

import re

from adapters.windows_service import _query, _run, _service_name

_ACTOR = re.compile(r"^relocation:[A-Za-z0-9._-]{1,180}$")
_MODES = {"AUTO_START": "auto", "DEMAND_START": "demand", "DISABLED": "disabled"}


def _state(instance_id):
    from instance_runtime import STATE_DIR, _read, _token
    path = STATE_DIR / "relocation-fences" / (_token(instance_id, "instance_id") + ".json")
    return path, _read(path)


def locked(instance_id):
    path, _ = _state(instance_id)
    return path.exists()


def fence(config, instance_id, actor):
    from instance_runtime import _owned, _write, lifecycle
    if not _ACTOR.fullmatch(str(actor or "")):
        raise PermissionError("relocation fencing requires matching Controller token")
    record = _owned(config, instance_id)
    service = _service_name(record)
    path, saved = _state(instance_id)
    if saved:
        if saved.get("actor") != actor or saved.get("service") != service:
            raise PermissionError("another relocation already fenced the source")
    elif path.exists():
        raise PermissionError("invalid source fence state requires operator recovery")
    else:
        qc = _run("qc", service)
        if qc.returncode:
            raise RuntimeError("cannot inspect source service startup configuration")
        match = re.search(r"START_TYPE\s*:\s*\d+\s+(\w+)",
                          (qc.stdout or "") + (qc.stderr or ""), re.I)
        original = (match.group(1).upper() if match else "")
        if original not in _MODES:
            raise RuntimeError("unsupported Windows service startup configuration")
        saved = {"actor": actor, "service": service, "previous": original, "phase": "preparing"}
        _write(path, saved)
    disabled = _run("config", service, "start=", "disabled")
    if disabled.returncode:
        raise RuntimeError("cannot disable original Windows service")
    state = _query(service)
    if not state.get("available"):
        raise RuntimeError("source service missing after disabling")
    if state.get("active_state") != "inactive":
        stopped = lifecycle(config, instance_id, "stop")
        if stopped.get("observed_state") != "stopped":
            raise RuntimeError("source service did not stop")
    final = _query(service)
    if not final.get("available") or final.get("active_state") != "inactive":
        raise RuntimeError("source service fencing was not confirmed")
    saved["phase"] = "fenced"
    _write(path, saved)
    return {"action": "fence", "observed_state": "stopped", "fenced": True,
            "service": service, "startup_was": saved["previous"]}


def unfence(config, instance_id, actor):
    from instance_runtime import _owned
    if not _ACTOR.fullmatch(str(actor or "")):
        raise PermissionError("invalid Controller relocation token")
    record = _owned(config, instance_id)
    service = _service_name(record)
    path, saved = _state(instance_id)
    if not saved or saved.get("actor") != actor or saved.get("service") != service:
        raise PermissionError("matching durable source fence is required to recover")
    state = _query(service)
    if not state.get("available") or state.get("active_state") != "inactive":
        raise RuntimeError("source service must remain stopped to restore original startup")
    original = _MODES.get(saved.get("previous"))
    if not original:
        raise RuntimeError("unknown original Windows startup mode")
    restored = _run("config", service, "start=", original)
    if restored.returncode:
        raise RuntimeError("cannot restore original Windows service startup mode")
    path.unlink()
    return {"action": "unfence", "observed_state": "stopped", "fenced": False,
            "service": service, "startup_restored": original}
