"""Agent-local durable source fencing for cross-host relocation.

A source unit is disabled before it is stopped so a host reboot cannot
automatically resurrect it after the Controller has moved the instance.
"""
from __future__ import annotations

import re
from adapters.systemd import SystemdAdapter, _default_runner, unit_for_instance

_TOKEN = re.compile(r"^relocation:[A-Za-z0-9._-]{1,180}$")


def _state(iid):
    from instance_runtime import STATE_DIR, _token, _read
    iid = _token(iid, "instance_id")
    path = STATE_DIR / "relocation-fences" / (iid + ".json")
    return path, _read(path)


def locked(instance_id):
    from instance_runtime import _token
    path, _ = _state(_token(instance_id, "instance_id"))
    # Corrupt state is a lock, not permission to restart a possibly moved source.
    return path.exists()


def fence(config, instance_id, actor):
    from instance_runtime import _owned, _write, lifecycle
    if not _TOKEN.fullmatch(str(actor or "")):
        raise PermissionError("relocation fencing requires a signed Controller phase")
    record = _owned(config, instance_id)
    unit = unit_for_instance(record)
    path, old = _state(instance_id)
    if old:
        if old.get("actor") != actor:
            raise PermissionError("source already fenced by another operation")
    elif path.exists():
        raise PermissionError("invalid source fence state requires operator recovery")
    else:
        code, stdout, stderr = _default_runner(["systemctl", "is-enabled", unit], 10)
        previous = str(stdout or "").strip().lower()
        if previous not in {"enabled", "disabled", "static", "indirect"}:
            raise RuntimeError("cannot establish previous instance startup state: " + str(stderr)[:400])
        old = {"actor": actor, "unit": unit, "previous": previous, "phase": "preparing"}
        _write(path, old)
    # The durable fence marker also blocks any future Agent-initiated starts.
    # A repeated command after process failure may safely repeat disable/stop.
    from privileged_materialization import disable_relocation_source
    disable_relocation_source(config, record)
    current = SystemdAdapter().status(record)
    if not current.get("available"):
        raise RuntimeError("source unit unavailable after disable")
    if current.get("running"):
        stopped = lifecycle(config, instance_id, "stop")
        if str(stopped.get("observed_state")) != "stopped":
            raise RuntimeError("source unit did not stop")
    state = SystemdAdapter().status(record)
    if not state.get("available") or state.get("running"):
        raise RuntimeError("source instance fencing not confirmed")
    old["phase"] = "fenced"
    _write(path, old)
    return {"action": "fence", "observed_state": "stopped", "fenced": True,
            "unit": unit, "startup_was": old["previous"]}


def unfence(config, instance_id, actor):
    from instance_runtime import _owned
    if not _TOKEN.fullmatch(str(actor or "")):
        raise PermissionError("invalid relocation recovery token")
    record = _owned(config, instance_id)
    path, fence_record = _state(instance_id)
    if not fence_record or fence_record.get("actor") != actor:
        raise PermissionError("original Agent fencing record missing or belongs to another operation")
    unit = unit_for_instance(record)
    if fence_record.get("unit") != unit:
        raise RuntimeError("source unit identity changed during relocation")
    state = SystemdAdapter().status(record)
    if not state.get("available") or state.get("running"):
        raise RuntimeError("source must be stopped before recovery")
    if fence_record.get("previous") == "enabled":
        from privileged_materialization import restore_relocation_source
        restore_relocation_source(config, record, restore_enabled=True)
    elif fence_record.get("previous") not in {"disabled", "static", "indirect"}:
        raise RuntimeError("unknown original source startup setting")
    path.unlink()
    return {"action": "unfence", "observed_state": "stopped", "fenced": False,
            "unit": unit, "startup_restored": fence_record["previous"]}
