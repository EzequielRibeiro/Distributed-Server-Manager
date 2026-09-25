"""Deterministic Agent-local projection of enabled Universal Content."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
STATE_ROOT = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", PROGRAM_DATA / "CapivaraAgent" / "state"))
CONTENT_STATE = STATE_ROOT / "managed-content"
ACTIVATION_STATE = STATE_ROOT / "content-activation"
_ALLOWED_ACTIVATION_KEYS = frozenset({"adapter", "mode", "identifier"})


def _safe_component(value: Any) -> str:
    text = str(value or "").strip()
    if not text or "/" in text or "\\" in text or text in {".", ".."}:
        raise ValueError("unsafe content activation identifier")
    return text


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _state_path(instance_id: Any, content_id: Any) -> Path:
    return CONTENT_STATE / _safe_component(instance_id) / f"{_safe_component(content_id)}.json"


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


def _activation(command: Mapping[str, Any]) -> dict[str, str]:
    metadata = command.get("metadata") if isinstance(command.get("metadata"), Mapping) else {}
    raw = command.get("activation") if isinstance(command.get("activation"), Mapping) else metadata.get("activation")
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, str] = {}
    for key in _ALLOWED_ACTIVATION_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result[key] = text[:191]
    return result


def _dayz_map_compatibility(command: Mapping[str, Any]) -> dict[str, Any]:
    metadata = command.get("metadata") if isinstance(command.get("metadata"), Mapping) else {}
    raw = command.get("dayz_map_compatibility") if isinstance(command.get("dayz_map_compatibility"), Mapping) else metadata.get("dayz_map_compatibility")
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Any] = {}
    if raw.get("all_missions") is True:
        result["all_missions"] = True
    for key in ("compatible_missions", "incompatible_missions"):
        values = raw.get(key)
        if not isinstance(values, list):
            continue
        clean: list[str] = []
        for value in values[:64]:
            text = str(value or "").strip()
            if text and len(text) <= 128 and all(ch.isalnum() or ch in "._-" for ch in text):
                if text not in clean:
                    clean.append(text)
        if clean:
            result[key] = clean
    return result


def _entry(state: dict[str, Any]) -> dict[str, Any] | None:
    status = str(state.get("status") or "")
    active_security = str(state.get("security_state") or "unscanned")
    if status in {"security_blocked", "security_scan_failed"}:
        # U10/U7 invariant: a rejected candidate revision must not remove the
        # previously applied clean revision from the native runtime projection.
        if not (int(state.get("applied_revision") or 0) > 0 and state.get("applied_checksum") and state.get("installed_version") and state.get("managed_path")):
            return None
        active_security = str(state.get("applied_security_state") or "unscanned")
    elif status != "applied":
        return None
    # U7: the *applied* revision is activatable only after an explicit clean
    # verdict. The desired candidate may independently be blocked/scan_failed.
    if int(state.get("security_policy_version") or 0) >= 1 and active_security != "clean":
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
        "dependencies": [str(value).strip() for value in (state.get("dependencies") or []) if str(value).strip()],
        "activation": activation,
        "dayz_map_compatibility": dict(state.get("dayz_map_compatibility") or {}) if isinstance(state.get("dayz_map_compatibility"), dict) else {},
    }


def _ordered_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = {str(item["content_id"]): item for item in entries}
    while True:
        blocked = [
            content_id
            for content_id, item in active.items()
            if any(str(dep) not in active for dep in item.get("dependencies") or [])
        ]
        if not blocked:
            break
        for content_id in blocked:
            active.pop(content_id, None)

    ordered: list[dict[str, Any]] = []
    permanent: set[str] = set()
    visiting: set[str] = set()

    def visit(content_id: str) -> None:
        if content_id in permanent:
            return
        if content_id in visiting:
            raise ValueError("content activation dependency cycle")
        visiting.add(content_id)
        item = active[content_id]
        deps = [str(dep) for dep in item.get("dependencies") or [] if str(dep) in active]
        deps.sort(key=lambda dep: (int(active[dep]["activation_order"]), dep))
        for dep in deps:
            visit(dep)
        visiting.remove(content_id)
        permanent.add(content_id)
        ordered.append(item)

    for item in sorted(active.values(), key=lambda value: (int(value["activation_order"]), str(value["content_id"]))):
        visit(str(item["content_id"]))
    return ordered


def build_activation_snapshot(instance_id: str) -> dict[str, Any]:
    iid = _safe_component(instance_id)
    entries = [entry for state in _load_instance_states(iid) if (entry := _entry(state)) is not None]
    entries = _ordered_entries(entries)
    identity = {
        "schema_version": 1,
        "kind": "CapivaraContentActivationSnapshot",
        "instance_id": iid,
        "entries": entries,
    }
    checksum = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {**identity, "checksum": checksum}


def refresh_activation_snapshot(instance_id: str) -> dict[str, Any]:
    snapshot = build_activation_snapshot(instance_id)
    _write(ACTIVATION_STATE / f"{snapshot['instance_id']}.json", snapshot)
    return snapshot


def synchronize_activation_state(commands: list[dict[str, Any]], reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist assignment activation semantics after content reconciliation."""
    command_index: dict[tuple[str, str], dict[str, Any]] = {}
    for command in commands:
        if not isinstance(command, dict):
            continue
        iid = str(command.get("instance_id") or "").strip()
        cid = str(command.get("content_id") or "").strip()
        if iid and cid:
            command_index[(iid, cid)] = command

    changed_instances: set[str] = set()
    for report in reports:
        if not isinstance(report, dict):
            continue
        report_status = str(report.get("status") or "")
        if report_status not in {"applied", "security_blocked", "security_scan_failed"}:
            continue
        iid = str(report.get("instance_id") or "").strip()
        cid = str(report.get("content_id") or "").strip()
        command = command_index.get((iid, cid))
        if command is None:
            continue
        path = _state_path(iid, cid)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(state, dict):
            continue
        desired_state = str(command.get("desired_state") or "installed").strip().lower()
        default_activation = "enabled" if desired_state == "installed" else "disabled"
        state["desired_state"] = desired_state
        state["activation_state"] = str(command.get("activation_state") or default_activation).strip().lower()
        state["activation_order"] = _order(command.get("activation_order"))
        state["dependencies"] = [str(value).strip() for value in (command.get("dependencies") or []) if str(value).strip()]
        state["activation"] = _activation(command)
        state["dayz_map_compatibility"] = _dayz_map_compatibility(command)
        _write(path, state)
        changed_instances.add(iid)

    return [refresh_activation_snapshot(iid) for iid in sorted(changed_instances)]


def activation_snapshot(instance_id: str) -> dict[str, Any]:
    iid = _safe_component(instance_id)
    path = ACTIVATION_STATE / f"{iid}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return build_activation_snapshot(iid)
    return value if isinstance(value, dict) else build_activation_snapshot(iid)


__all__ = [
    "activation_snapshot",
    "build_activation_snapshot",
    "refresh_activation_snapshot",
    "synchronize_activation_state",
]
