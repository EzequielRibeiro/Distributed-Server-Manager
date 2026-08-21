#!/usr/bin/env python3
"""Game-agnostic materialization and desired/observed reconciliation for Agent instances."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import instance_runtime
from adapters import resolve_adapter
from materializers import resolve_materializer
from runtime_events import emit_runtime_event
from runtime_spec import validate_runtime_spec


def _state_dir() -> Path:
    return Path(instance_runtime.STATE_DIR)


def materialize(config: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(config.get("agent_id") or "").strip()
    normalized = validate_runtime_spec(spec, expected_agent_id=agent_id)
    emit_runtime_event(_state_dir(), "INSTANCE_RUNTIME_MATERIALIZING", instance_id=normalized["instance_id"], agent_id=agent_id)
    materializer = resolve_materializer(normalized)
    try:
        operation = materializer.apply(normalized)
        record = instance_runtime.register_instance({
            **normalized,
            "observed_state": "unknown",
            "materialized": True,
        })
        event = emit_runtime_event(
            _state_dir(), "INSTANCE_RUNTIME_READY", instance_id=normalized["instance_id"], agent_id=agent_id,
            data={"adapter": normalized["adapter"], "changed": bool(operation.get("changed"))},
        )
        return {"spec": normalized, "instance": record, "operation": operation, "event": event}
    except Exception as exc:
        emit_runtime_event(
            _state_dir(), "INSTANCE_RUNTIME_FAILED", instance_id=normalized["instance_id"], agent_id=agent_id,
            data={"phase": "materialize", "error": str(exc)[:2000]},
        )
        raise


def reconcile(config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    record = instance_runtime._owned(config, instance_id)
    normalized = validate_runtime_spec(record, expected_agent_id=str(config.get("agent_id") or ""))
    materializer = resolve_materializer(normalized)
    materialized = materializer.inspect(normalized)
    if not materialized.get("exists") or not materialized.get("owned"):
        raise RuntimeError("instance runtime is not safely materialized")
    adapter = resolve_adapter(normalized)
    before = adapter.status(normalized)
    desired = normalized["desired_state"]
    running = bool(before.get("running"))
    operation: dict[str, Any] | None = None
    if desired == "running" and not running:
        operation = adapter.start(normalized)
    elif desired == "stopped" and running:
        operation = adapter.stop(normalized)
    after = adapter.status(normalized)
    observed = instance_runtime._observed_state(after, record.get("observed_state"))
    updated = instance_runtime.register_instance({**record, "observed_state": observed})
    event_type = "INSTANCE_RUNTIME_RECONCILED" if operation else "INSTANCE_RUNTIME_IN_SYNC"
    event = emit_runtime_event(
        _state_dir(), event_type, instance_id=normalized["instance_id"], agent_id=normalized["agent_id"],
        data={"desired_state": desired, "observed_state": observed, "changed": operation is not None},
    )
    return {
        "instance_id": normalized["instance_id"],
        "desired_state": desired,
        "observed_state": observed,
        "changed": operation is not None,
        "operation": operation,
        "instance": updated,
        "event": event,
    }


def remove(config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    record = instance_runtime._owned(config, instance_id)
    normalized = validate_runtime_spec(record, expected_agent_id=str(config.get("agent_id") or ""))
    adapter = resolve_adapter(normalized)
    state = adapter.status(normalized)
    stopped = None
    if bool(state.get("running")):
        stopped = adapter.stop(normalized)
    operation = resolve_materializer(normalized).remove(normalized)
    try:
        instance_runtime._instance_path(instance_id).unlink()
    except FileNotFoundError:
        pass
    event = emit_runtime_event(
        _state_dir(), "INSTANCE_RUNTIME_REMOVED", instance_id=normalized["instance_id"], agent_id=normalized["agent_id"],
        data={"changed": bool(operation.get("changed"))},
    )
    return {"instance_id": normalized["instance_id"], "stop": stopped, "operation": operation, "event": event}


__all__ = ["materialize", "reconcile", "remove"]
