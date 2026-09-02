#!/usr/bin/env python3
"""Typed two-phase remote uninstall client for the Linux Agent."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
UNINSTALL_DIR = STATE_DIR / "uninstall"
RESULT_PATH = UNINSTALL_DIR / "result.json"
REQUEST_PATH = UNINSTALL_DIR / "request.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def read_result() -> dict[str, Any] | None:
    return _read(RESULT_PATH)


def clear_result(request_id: str) -> None:
    current = read_result()
    if not current or str(current.get("request_id") or "") != str(request_id or ""):
        return
    try:
        RESULT_PATH.unlink()
    except FileNotFoundError:
        pass


def _validate(command: dict[str, Any]) -> tuple[str, str, str]:
    if command.get("kind") != "AgentUninstallCommand":
        raise ValueError("unsupported uninstall command kind")
    if int(command.get("schema_version") or 0) != 1:
        raise ValueError("unsupported uninstall command schema")
    if str(command.get("action") or "") != "uninstall-agent":
        raise ValueError("unsupported uninstall action")
    request_id = str(command.get("request_id") or "").strip()
    phase = str(command.get("phase") or "").strip().lower()
    mode = str(command.get("mode") or "").strip().lower()
    if not request_id.startswith("uninstall-"):
        raise ValueError("invalid uninstall request_id")
    if phase not in {"prepare", "commit"}:
        raise ValueError("invalid uninstall phase")
    if mode not in {"preserve-data", "purge"}:
        raise ValueError("invalid uninstall mode")
    return request_id, phase, mode


def handle_command(config: dict[str, Any], command: dict[str, Any], *, host_identity: str | None = None) -> dict[str, Any]:
    """Accept prepare or stage privileged commit without arbitrary shell input."""
    request_id, phase, mode = _validate(command)
    current = read_result()
    if current and str(current.get("request_id") or "") == request_id:
        status = str(current.get("status") or "")
        if phase == "prepare" and status in {"accepted", "committed", "completed"}:
            return current
        if phase == "commit" and status in {"committed", "completed"}:
            return current

    if phase == "prepare":
        result = {
            "request_id": request_id,
            "status": "accepted",
            "accepted_at": _now(),
            "mode": mode,
        }
        _write(RESULT_PATH, result)
        return result

    required = ("agent_id", "controller_url", "credential_id", "credential_secret", "fingerprint")
    missing = [key for key in required if not str(config.get(key) or "").strip()]
    if missing:
        raise RuntimeError("cannot commit uninstall without permanent Agent credential")

    request = {
        "schema_version": 1,
        "kind": "CapivaraLinuxUninstallRequest",
        "request_id": request_id,
        "mode": mode,
        "agent_id": str(config["agent_id"]),
        "controller_url": str(config["controller_url"]),
        "credential_id": str(config["credential_id"]),
        "credential_secret": str(config["credential_secret"]),
        "fingerprint": str(config["fingerprint"]),
        "host_identity": str(host_identity or ""),
        "instance_storage_root": str(config.get("instance_storage_root") or "/var/lib/capivara-instances"),
        "requested_at": _now(),
    }
    _write(REQUEST_PATH, request)
    result = {
        "request_id": request_id,
        "status": "committed",
        "committed_at": _now(),
        "mode": mode,
    }
    _write(RESULT_PATH, result)
    return result


__all__ = ["clear_result", "handle_command", "read_result", "REQUEST_PATH", "RESULT_PATH"]
