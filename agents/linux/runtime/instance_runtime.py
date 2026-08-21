#!/usr/bin/env python3
"""Agent-owned, game-agnostic instance observation and command state."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
INSTANCE_DIR = STATE_DIR / "instances"
RESULT_DIR = STATE_DIR / "instance-results"
HISTORY_DIR = STATE_DIR / "instance-command-history"
_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
VALID_ACTIONS = {"status", "doctor"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _token(value: Any, label: str) -> str:
    value = str(value or "").strip()
    if not _TOKEN.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _instance_path(instance_id: str) -> Path:
    return INSTANCE_DIR / f"{_token(instance_id, 'instance_id')}.json"


def get_instance(instance_id: str) -> dict[str, Any] | None:
    return _read(_instance_path(instance_id))


def register_instance(record: dict[str, Any]) -> dict[str, Any]:
    """Persist the Agent-local instance identity used by future provisioning."""
    body = dict(record or {})
    instance_id = _token(body.get("instance_id"), "instance_id")
    body["instance_id"] = instance_id
    body["agent_id"] = _token(body.get("agent_id"), "agent_id")
    body.setdefault("schema_version", 1)
    body.setdefault("kind", "CapivaraAgentInstance")
    body["updated_at"] = _now()
    body.setdefault("created_at", body["updated_at"])
    _write(_instance_path(instance_id), body)
    return body


def _owned(config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    record = get_instance(instance_id)
    if record is None:
        raise LookupError(f"instance not found: {instance_id}")
    local_agent = str(config.get("agent_id") or "").strip()
    if not local_agent or str(record.get("agent_id") or "") != local_agent:
        raise PermissionError("instance belongs to another Agent")
    return record


def list_instances(config: dict[str, Any]) -> list[dict[str, Any]]:
    local_agent = str(config.get("agent_id") or "").strip()
    values: list[dict[str, Any]] = []
    try:
        paths = sorted(INSTANCE_DIR.glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        item = _read(path)
        if item and str(item.get("agent_id") or "") == local_agent:
            values.append({
                "instance_id": item.get("instance_id"),
                "game_id": item.get("game_id"),
                "environment_id": item.get("environment_id"),
                "adapter": item.get("adapter"),
                "observed_state": item.get("observed_state", "unknown"),
            })
    return values


def status(config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    record = _owned(config, instance_id)
    configured_path = str(record.get("path") or "").strip()
    return {
        "schema_version": 1,
        "kind": "CapivaraInstanceStatus",
        "scope": "instance-local",
        "instance_id": record["instance_id"],
        "agent_id": record["agent_id"],
        "game_id": record.get("game_id"),
        "environment_id": record.get("environment_id"),
        "runtime_id": record.get("runtime_id"),
        "adapter": record.get("adapter"),
        "desired_state": record.get("desired_state"),
        "observed_state": record.get("observed_state", "unknown"),
        "path": configured_path or None,
        "path_exists": bool(configured_path and Path(configured_path).exists()),
        "updated_at": record.get("updated_at"),
    }


def doctor(config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    view = status(config, instance_id)
    findings: list[dict[str, str]] = []
    if not view.get("adapter"):
        findings.append({"code": "adapter_unconfigured", "severity": "warning", "message": "Instance runtime adapter is not configured."})
    if not view.get("runtime_id"):
        findings.append({"code": "runtime_unconfigured", "severity": "warning", "message": "Instance runtime identity is not configured."})
    if view.get("path") and not view.get("path_exists"):
        findings.append({"code": "instance_path_missing", "severity": "critical", "message": "Configured instance path does not exist."})
    severities = {item["severity"] for item in findings}
    state = "critical" if "critical" in severities else "degraded" if "warning" in severities else "healthy"
    return {
        "schema_version": 1,
        "kind": "CapivaraInstanceDoctor",
        "scope": "instance-local",
        "status": state,
        "ready": state != "critical",
        "instance": view,
        "findings": findings,
    }


def inventory(config: dict[str, Any]) -> list[dict[str, Any]]:
    return list_instances(config)


def _history(command_id: str) -> Path:
    return HISTORY_DIR / f"{_token(command_id, 'command_id')}.json"


def _result(command_id: str) -> Path:
    return RESULT_DIR / f"{_token(command_id, 'command_id')}.json"


def handle_command(config: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    command_id = _token(command.get("command_id"), "command_id")
    previous = _read(_history(command_id))
    if previous is not None:
        _write(_result(command_id), previous)
        return previous
    instance_id = str(command.get("instance_id") or "").strip()
    action = str(command.get("action") or "").strip().lower()
    try:
        _token(instance_id, "instance_id")
        if action not in VALID_ACTIONS:
            raise ValueError("unsupported instance action")
        payload = status(config, instance_id) if action == "status" else doctor(config, instance_id)
        result = {
            "command_id": command_id,
            "instance_id": instance_id,
            "action": action,
            "status": "completed",
            "result": payload,
            "generated_at": _now(),
        }
    except Exception as exc:
        result = {
            "command_id": command_id,
            "instance_id": instance_id or None,
            "action": action or None,
            "status": "failed",
            "error": str(exc)[:2000],
            "generated_at": _now(),
        }
    _write(_history(command_id), result)
    _write(_result(command_id), result)
    return result


def read_result() -> dict[str, Any] | None:
    try:
        paths = sorted(RESULT_DIR.glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        value = _read(path)
        if value:
            return value
    return None


def clear_result(command_id: str) -> None:
    try:
        _result(command_id).unlink()
    except FileNotFoundError:
        pass


__all__ = [
    "VALID_ACTIONS", "clear_result", "doctor", "get_instance", "handle_command", "inventory",
    "list_instances", "read_result", "register_instance", "status",
]
