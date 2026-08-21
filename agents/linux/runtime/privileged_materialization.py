#!/usr/bin/env python3
"""Bridge unprivileged Agent provisioning to the root-owned materializer helper."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import instance_runtime
from adapters import resolve_adapter
from runtime_events import emit_runtime_event
from runtime_spec import validate_runtime_spec


def _request_root() -> Path:
    return Path(instance_runtime.STATE_DIR) / "privileged-materialization"


def _token(value: Any) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or len(text) > 191 or any(ch not in allowed for ch in text):
        raise ValueError("invalid instance_id")
    return text


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _invoke(action: str, spec: dict[str, Any]) -> dict[str, Any]:
    instance_id = _token(spec["instance_id"])
    root = _request_root()
    request_path = root / f"{instance_id}.request.json"
    result_path = root / f"{instance_id}.result.json"
    try:
        result_path.unlink()
    except FileNotFoundError:
        pass
    _atomic_json(
        request_path,
        {
            "schema_version": 1,
            "kind": "CapivaraPrivilegedMaterializationRequest",
            "action": action,
            "instance_id": instance_id,
            "agent_id": spec["agent_id"],
            "spec": spec,
        },
    )
    completed = subprocess.run(
        ["systemctl", "start", f"capivara-agent-materialize@{instance_id}.service", "--no-pager"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "privileged materializer helper failed")[:2000])
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"privileged materializer returned no valid result: {exc}") from exc
    if not isinstance(result, dict) or str(result.get("status") or "") != "completed":
        raise RuntimeError(str((result or {}).get("error") or "privileged materializer failed")[:2000])
    operation = result.get("operation")
    if not isinstance(operation, dict):
        raise RuntimeError("privileged materializer returned invalid operation")
    return operation


def materialize(config: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(config.get("agent_id") or "").strip()
    normalized = validate_runtime_spec(spec, expected_agent_id=agent_id)
    emit_runtime_event(
        Path(instance_runtime.STATE_DIR), "INSTANCE_RUNTIME_MATERIALIZING",
        instance_id=normalized["instance_id"], agent_id=agent_id,
    )
    try:
        operation = _invoke("apply", normalized)
        record = instance_runtime.register_instance({**normalized, "observed_state": "unknown", "materialized": True})
        event = emit_runtime_event(
            Path(instance_runtime.STATE_DIR), "INSTANCE_RUNTIME_READY",
            instance_id=normalized["instance_id"], agent_id=agent_id,
            data={"adapter": normalized["adapter"], "changed": bool(operation.get("changed"))},
        )
        return {"spec": normalized, "instance": record, "operation": operation, "event": event}
    except Exception as exc:
        emit_runtime_event(
            Path(instance_runtime.STATE_DIR), "INSTANCE_RUNTIME_FAILED",
            instance_id=normalized["instance_id"], agent_id=agent_id,
            data={"phase": "privileged-materialize", "error": str(exc)[:2000]},
        )
        raise


def remove(config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    record = instance_runtime._owned(config, instance_id)
    normalized = validate_runtime_spec(record, expected_agent_id=str(config.get("agent_id") or ""))
    adapter = resolve_adapter(normalized)
    state = adapter.status(normalized)
    stopped = adapter.stop(normalized) if bool(state.get("running")) else None
    operation = _invoke("remove", normalized)
    try:
        instance_runtime._instance_path(instance_id).unlink()
    except FileNotFoundError:
        pass
    event = emit_runtime_event(
        Path(instance_runtime.STATE_DIR), "INSTANCE_RUNTIME_REMOVED",
        instance_id=normalized["instance_id"], agent_id=normalized["agent_id"],
        data={"changed": bool(operation.get("changed"))},
    )
    return {"instance_id": normalized["instance_id"], "stop": stopped, "operation": operation, "event": event}


__all__ = ["materialize", "remove"]
