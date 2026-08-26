#!/usr/bin/env python3
"""Agent-side durable application/reporting for Controller-managed configuration."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_AGENT_STORAGE_NAMESPACE = "capivara.agent.storage"
_DEFAULT_INSTANCE_STORAGE_ROOT = "/var/lib/capivara-instances"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _root() -> Path:
    return Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent")) / "managed-configuration"


def _config_path() -> Path:
    return Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))


def _runtime_inventory_root() -> Path:
    return Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent")) / "instances"


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


def _instance_storage_root(value: Any) -> Path:
    text = str(value or _DEFAULT_INSTANCE_STORAGE_ROOT).strip()
    path = Path(text)
    if not path.is_absolute():
        raise ValueError("instance_storage_root must be an absolute path")
    resolved = path.resolve(strict=False)
    if resolved == Path("/"):
        raise ValueError("instance_storage_root cannot be filesystem root")
    return resolved


def _existing_instance_roots() -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    inventory = _runtime_inventory_root()
    if not inventory.is_dir():
        return result
    for path in inventory.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        instance_id = str(record.get("instance_id") or path.stem).strip()
        raw = record.get("instance_state_root")
        if not raw:
            continue
        state_root = Path(str(raw)).resolve(strict=False)
        result.append((instance_id, state_root))
    return result


def _load_local_config(target_id: str) -> dict[str, Any]:
    try:
        config = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Agent configuration is unavailable") from exc
    if not isinstance(config, dict):
        raise RuntimeError("Agent configuration is invalid")
    if str(config.get("agent_id") or "").strip() != target_id:
        raise PermissionError("configuration target does not match local Agent")
    return config


def _apply_agent_storage(value: dict[str, Any], target_id: str, revision: str) -> dict[str, Any]:
    desired_root = _instance_storage_root(value.get("instance_storage_root"))
    config = _load_local_config(target_id)
    migrate_existing = bool(value.get("migrate_existing"))
    if migrate_existing:
        from storage_migration_client import handle_command
        migration = handle_command(
            config,
            {
                "migration_id": f"configuration-{revision}",
                "action": "migrate-instance-storage",
                "target_root": str(desired_root),
            },
        )
        if str(migration.get("status") or "") != "completed":
            raise RuntimeError(str(migration.get("error") or "instance storage migration failed"))
        return {
            "instance_storage_root": str(desired_root),
            "migrate_existing": False,
            "migration": migration,
        }

    blockers = []
    for instance_id, state_root in _existing_instance_roots():
        expected = (desired_root / instance_id).resolve(strict=False)
        if state_root != expected:
            blockers.append(instance_id)
    if blockers:
        preview = ", ".join(blockers[:5])
        suffix = "" if len(blockers) <= 5 else f" (+{len(blockers) - 5})"
        raise RuntimeError(f"instance storage migration required before changing root: {preview}{suffix}")

    desired_root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(desired_root, 0o711)
    except OSError:
        pass
    config["instance_storage_root"] = str(desired_root)
    _atomic_json(_config_path(), config)
    return {"instance_storage_root": str(desired_root), "migrate_existing": False}


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
    if namespace == _AGENT_STORAGE_NAMESPACE:
        if target_type != "agent":
            raise ValueError("Agent storage configuration requires agent target")
        applied_value = _apply_agent_storage(value, target_id, revision)
    else:
        applied_value = value
    document = {
        "schema_version": 1,
        "kind": "CapivaraAppliedConfiguration",
        "namespace": namespace,
        "target_type": target_type,
        "target_id": target_id,
        "revision": revision,
        "checksum": checksum,
        "value": applied_value,
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
        try:
            report = apply_configuration(command)
        except Exception as exc:
            target_type = str(command.get("target_type") or "")
            target_id = str(command.get("target_id") or "")
            namespace = str(command.get("namespace") or "")
            revision = str(command.get("revision") or "")
            checksum = str(command.get("checksum") or "")
            report = {
                "target_type": target_type,
                "target_id": target_id,
                "namespace": namespace,
                "desired_revision": revision,
                "applied_revision": None,
                "desired_checksum": checksum,
                "applied_checksum": None,
                "status": "failed",
                "last_error": str(exc)[:1000],
                "reported_at": _now(),
                "configuration_refs": list(command.get("configuration_refs") or []),
            }
        key = (report["target_type"], report["target_id"], report["namespace"])
        states[key] = report
        changed = True
    reports = [states[key] for key in sorted(states)]
    if changed:
        _atomic_json(_root() / "state.json", {"schema_version": 1, "reports": reports, "reported_at": _now()})
    return reports


__all__ = ["apply_configuration", "apply_configuration_commands", "configuration_state"]