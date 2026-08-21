#!/usr/bin/env python3
"""Stage Agent instance provisioning requests for the privileged provisioner."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from instance_runtime import register_instance, unregister_instance

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
ROOT = STATE_DIR / "instance-provisioning"
REQUEST_DIR = ROOT / "requests"
RESULT_DIR = ROOT / "results"
HISTORY_DIR = ROOT / "history"
_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
VALID_ACTIONS = {"provision", "reconcile", "remove"}


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise ValueError(f"invalid {label}")
    return text


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _paths(job_id: str) -> tuple[Path, Path, Path]:
    safe = _token(job_id, "job_id")
    return REQUEST_DIR / f"{safe}.json", RESULT_DIR / f"{safe}.json", HISTORY_DIR / f"{safe}.json"


def stage_instance_provisioning_command(config: dict[str, Any], command: dict[str, Any] | None) -> bool:
    if not isinstance(command, dict):
        return False
    job_id = _token(command.get("job_id"), "job_id")
    instance_id = _token(command.get("instance_id"), "instance_id")
    agent_id = _token(command.get("agent_id"), "agent_id")
    if agent_id != str(config.get("agent_id") or ""):
        raise PermissionError("provisioning command belongs to another Agent")
    action = str(command.get("action") or "").strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError("unsupported instance provisioning action")
    if action != "remove" and not isinstance(command.get("runtime"), dict):
        raise ValueError("runtime contract is required")
    request_path, result_path, history_path = _paths(job_id)
    previous = _read(history_path) or _read(result_path)
    if previous and str(previous.get("status") or "").lower() in {"completed", "failed"}:
        return False
    if request_path.exists():
        return False
    body = dict(command)
    body.update({"job_id": job_id, "instance_id": instance_id, "agent_id": agent_id, "action": action})
    _write(request_path, body)
    return True


def _apply_local_state(result: dict[str, Any]) -> dict[str, Any]:
    if str(result.get("status") or "").lower() != "completed" or result.get("local_state_applied"):
        return result
    action = str(result.get("action") or "").strip().lower()
    instance_id = _token(result.get("instance_id"), "instance_id")
    if action in {"provision", "reconcile"}:
        record = result.get("instance_record")
        if not isinstance(record, dict):
            return result
        register_instance(record)
    elif action == "remove":
        unregister_instance(instance_id)
    updated = dict(result)
    updated["local_state_applied"] = True
    _, result_path, history_path = _paths(str(result["job_id"]))
    _write(result_path, updated)
    _write(history_path, updated)
    return updated


def read_instance_provisioning_result() -> dict[str, Any] | None:
    if not RESULT_DIR.is_dir():
        return None
    candidates: list[tuple[float, dict[str, Any]]] = []
    for path in RESULT_DIR.glob("*.json"):
        value = _read(path)
        if value:
            try:
                stamp = path.stat().st_mtime
            except OSError:
                stamp = 0.0
            candidates.append((stamp, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return _apply_local_state(candidates[0][1])


def clear_instance_provisioning_result(job_id: str) -> None:
    try:
        request_path, result_path, _ = _paths(job_id)
    except ValueError:
        return
    for path in (request_path, result_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "VALID_ACTIONS", "clear_instance_provisioning_result", "read_instance_provisioning_result",
    "stage_instance_provisioning_command",
]
