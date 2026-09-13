#!/usr/bin/env python3
"""Deterministic Agent-local projection of enabled Universal Content.

This module is deliberately game-agnostic. Game-specific activation adapters
consume its snapshot later in the runtime reconciliation path.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

STATE_ROOT = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
CONTENT_STATE = STATE_ROOT / "managed-content"
ACTIVATION_STATE = STATE_ROOT / "content-activation"


def _safe_component(value: Any) -> str:
    text = str(value or "").strip()
    if not text or "/" in text or "\\" in text or text in {".", ".."}:
        raise ValueError("unsafe content activation identifier")
    return text


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _load_instance_states(instance_id: str) -> list[dict[str, Any]]:
    root = CONTENT_STATE / _safe_component(instance_id)
    try:
        paths = sorted(root.glob("*.json"))
    except OSError:
        return []
    result: list[dict[str, Any]] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _order(value: Any) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(result, 1_000_000))


def _entry(state: dict[str, Any]) -> dict[str, Any] | None:
    if str(state.get("status") or "") != "applied":
        return None
    if str(state.get("desired_state") or "installed") != "installed":
        return None
    if str(state.get("activation_state") or "enabled") != "enabled":
        return None
    if not state.get("installed_version"):
        return None
    content_id = _safe_component(state.get("content_id"))
    activation = state.get("activation") if isinstance(state.get("activation"), dict) else {}
    return {
        "content_id": content_id,
        "game_id": str(state.get("game_id") or "").strip().lower() or None,
        "content_type": str(state.get("content_type") or "other").strip().lower(),
        "provider": str(state.get("provider") or "").strip().lower() or None,
        "package_id": str(state.get("package_id") or "").strip() or None,
        "target": str(state.get("target") or "").strip() or None,
        "managed_path": str(state.get("managed_path") or "").strip() or None,
        "activation_order": _order(state.get("activation_order")),
        "activation": activation,
    }


def build_activation_snapshot(instance_id: str) -> dict[str, Any]:
    iid = _safe_component(instance_id)
    entries = [entry for state in _load_instance_states(iid) if (entry := _entry(state)) is not None]
    entries.sort(key=lambda item: (int(item["activation_order"]), str(item["content_id"])))
    identity = {"schema_version": 1, "kind": "CapivaraContentActivationSnapshot", "instance_id": iid, "entries": entries}
    checksum = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    return {**identity, "checksum": checksum}


def refresh_activation_snapshot(instance_id: str) -> dict[str, Any]:
    snapshot = build_activation_snapshot(instance_id)
    _write(ACTIVATION_STATE / f"{snapshot['instance_id']}.json", snapshot)
    return snapshot


def activation_snapshot(instance_id: str) -> dict[str, Any]:
    iid = _safe_component(instance_id)
    path = ACTIVATION_STATE / f"{iid}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return build_activation_snapshot(iid)
    return value if isinstance(value, dict) else build_activation_snapshot(iid)


__all__ = ["activation_snapshot", "build_activation_snapshot", "refresh_activation_snapshot"]
