#!/usr/bin/env python3
"""Agent-side durable application/reporting for Controller-managed configuration."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _root() -> Path:
    return Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent")) / "managed-configuration"


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def _path(command: dict[str, Any]) -> Path:
    target_type = _safe(str(command.get("target_type") or "agent"))
    target_id = _safe(str(command.get("target_id") or "unknown"))
    namespace = _safe(str(command.get("namespace") or "default"))
    return _root() / target_type / target_id / f"{namespace}.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".config-", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def configuration_state() -> list[dict[str, Any]]:
    path = _root() / "state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    reports = payload.get("reports") if isinstance(payload, dict) else None
    return [dict(item) for item in reports if isinstance(item, dict)] if isinstance(reports, list) else []


def apply_configuration(command: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(command, dict):
        raise ValueError("configuration command must be an object")
    value = command.get("value")
    if not isinstance(value, dict):
        raise ValueError("configuration value must be an object")
    namespace = str(command.get("namespace") or "").strip().lower()
    checksum = str(command.get("checksum") or "").strip()
    revision = str(command.get("revision") or "").strip()
    target_type = str(command.get("target_type") or "").strip().lower()
    target_id = str(command.get("target_id") or "").strip()
    if target_type not in {"agent", "instance"} or not target_id:
        raise ValueError("configuration target is invalid")
    if not namespace or not checksum or not revision:
        raise ValueError("configuration namespace/revision/checksum required")
    document = {
        "schema_version": 1,
        "kind": "CapivaraAppliedConfiguration",
        "namespace": namespace,
        "target_type": target_type,
        "target_id": target_id,
        "revision": revision,
        "checksum": checksum,
        "value": value,
        "applied_at": _now(),
        "configuration_refs": list(command.get("configuration_refs") or []),
    }
    _atomic_json(_path(command), document)
    return {
        "target_type": target_type,
        "target_id": target_id,
        "namespace": namespace,
        "desired_revision": revision,
        "applied_revision": revision,
        "desired_checksum": checksum,
        "applied_checksum": checksum,
        "status": "applied",
        "last_error": None,
        "reported_at": document["applied_at"],
        "configuration_refs": document["configuration_refs"],
    }


def apply_configuration_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states = {
        (str(item.get("target_type") or ""), str(item.get("target_id") or ""), str(item.get("namespace") or "")): item
        for item in configuration_state()
    }
    changed = False
    for command in commands[:1000]:
        report = apply_configuration(command)
        key = (report["target_type"], report["target_id"], report["namespace"])
        states[key] = report
        changed = True
    reports = [states[key] for key in sorted(states)]
    if changed:
        _atomic_json(_root() / "state.json", {"schema_version": 1, "reports": reports, "reported_at": _now()})
    return reports


__all__ = ["apply_configuration", "apply_configuration_commands", "configuration_state"]
