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


def apply_configuration(command: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(command, dict):
        raise ValueError("configuration command must be an object")
    value = command.get("value")
    if not isinstance(value, dict):
        raise ValueError("configuration value must be an object")
    namespace = str(command.get("namespace") or "").strip()
    checksum = str(command.get("checksum") or "").strip()
    if not namespace or not checksum:
        raise ValueError("configuration namespace/checksum required")
    document = {
        "schema_version": 1,
        "kind": "CapivaraAppliedConfiguration",
        "namespace": namespace,
        "target_type": str(command.get("target_type") or "agent"),
        "target_id": str(command.get("target_id") or ""),
        "revision": str(command.get("revision") or ""),
        "checksum": checksum,
        "value": value,
        "applied_at": _now(),
        "configuration_refs": list(command.get("configuration_refs") or []),
    }
    _atomic_json(_path(command), document)
    reports = []
    for ref in document["configuration_refs"]:
        if not isinstance(ref, dict) or not ref.get("configuration_id"):
            continue
        reports.append({
            "configuration_id": str(ref["configuration_id"]),
            "desired_revision": int(ref.get("revision") or 0),
            "applied_revision": int(ref.get("revision") or 0),
            "status": "applied",
            "applied_checksum": str(ref.get("checksum") or ""),
            "reported_at": document["applied_at"],
        })
    return reports


def apply_configuration_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for command in commands[:1000]:
        reports.extend(apply_configuration(command))
    if reports:
        _atomic_json(_root() / "state.json", {"reports": reports, "reported_at": _now()})
    return reports


def configuration_state() -> list[dict[str, Any]]:
    path = _root() / "state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    reports = payload.get("reports") if isinstance(payload, dict) else None
    return [dict(item) for item in reports if isinstance(item, dict)] if isinstance(reports, list) else []


__all__ = ["apply_configuration", "apply_configuration_commands", "configuration_state"]
