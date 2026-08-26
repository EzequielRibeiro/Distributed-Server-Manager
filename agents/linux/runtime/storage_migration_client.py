#!/usr/bin/env python3
"""Safely migrate all instance-private state to a new Agent storage root."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import instance_runtime
from privileged_materialization import migrate_storage_copy, materialize
from runtime_limits import runtime_limits
from runtime_operations import runtime_operation

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
RESULT_PATH = STATE_DIR / "storage-migration-result.json"
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
DEFAULT_ROOT = Path("/var/lib/capivara-instances")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _root(value: Any) -> Path:
    text = str(value or "").strip()
    path = Path(text)
    if not text or not path.is_absolute():
        raise ValueError("instance storage root must be an absolute path")
    resolved = path.resolve(strict=False)
    if resolved == Path("/"):
        raise ValueError("filesystem root cannot be used as instance storage root")
    return resolved


def _replace_prefix(value: Any, source: Path, target: Path) -> Any:
    if isinstance(value, str):
        old = str(source)
        new = str(target)
        if value == old:
            return new
        if value.startswith(old + os.sep):
            return new + value[len(old):]
        marker = "=" + old
        position = value.find(marker)
        if position >= 0:
            suffix_index = position + len(marker)
            if suffix_index == len(value) or value[suffix_index:suffix_index + 1] == os.sep:
                return value[:position] + "=" + new + value[suffix_index:]
        return value
    if isinstance(value, list):
        return [_replace_prefix(item, source, target) for item in value]
    if isinstance(value, dict):
        return {key: _replace_prefix(item, source, target) for key, item in value.items()}
    return value


def _owned_records(config: dict[str, Any]) -> list[dict[str, Any]]:
    values = []
    agent_id = str(config.get("agent_id") or "").strip()
    for path in sorted(instance_runtime.INSTANCE_DIR.glob("*.json")):
        record = instance_runtime._read(path)
        if record and str(record.get("agent_id") or "") == agent_id:
            values.append(record)
    return values


def _write_config(config: dict[str, Any]) -> None:
    current = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    current["instance_storage_root"] = str(config["instance_storage_root"])
    _atomic_json(CONFIG_PATH, current)


def read_result() -> dict[str, Any] | None:
    try:
        value = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def clear_result(migration_id: str) -> None:
    current = read_result()
    if current and str(current.get("migration_id") or "") == str(migration_id):
        try:
            RESULT_PATH.unlink()
        except FileNotFoundError:
            pass


def handle_command(config: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    migration_id = str(command.get("migration_id") or "").strip()
    if not migration_id:
        raise ValueError("migration_id is required")
    target_root = _root(command.get("target_root"))
    source_root = _root(config.get("instance_storage_root") or DEFAULT_ROOT)
    if source_root == target_root:
        result = {"migration_id": migration_id, "status": "completed", "source_root": str(source_root), "target_root": str(target_root), "instances": [], "changed": False}
        _atomic_json(RESULT_PATH, result)
        return result

    records = _owned_records(config)
    for record in records:
        state = instance_runtime.status(config, str(record["instance_id"]))
        if str(state.get("observed_state") or "").lower() not in {"stopped", "offline", "unknown", "unavailable"}:
            raise RuntimeError(f"instance must be stopped before storage migration: {record['instance_id']}")

    limits = runtime_limits(config)
    copied: list[str] = []
    originals = {str(record["instance_id"]): dict(record) for record in records}
    try:
        for record in records:
            instance_id = str(record["instance_id"])
            state_root = Path(str(record.get("instance_state_root") or source_root / instance_id)).resolve(strict=False)
            expected = (source_root / instance_id).resolve(strict=False)
            if state_root != expected:
                raise RuntimeError(f"instance state root is outside current Agent storage root: {instance_id}")
            with runtime_operation(config, instance_id, "storage-migrate-copy", lock_timeout_seconds=limits.lock_timeout_seconds):
                migrate_storage_copy(config, record, target_root=str(target_root))
            copied.append(instance_id)

        new_config = dict(config)
        new_config["instance_storage_root"] = str(target_root)
        _write_config(new_config)
        config["instance_storage_root"] = str(target_root)

        migrated = []
        for record in records:
            instance_id = str(record["instance_id"])
            old_state = source_root / instance_id
            new_state = target_root / instance_id
            updated = _replace_prefix(record, old_state, new_state)
            instance_runtime.register_instance(updated)
            materialize(config, updated)
            migrated.append(instance_id)

        result = {
            "migration_id": migration_id,
            "status": "completed",
            "source_root": str(source_root),
            "target_root": str(target_root),
            "instances": migrated,
            "changed": True,
            "source_preserved": True,
        }
        _atomic_json(RESULT_PATH, result)
        return result
    except Exception as exc:
        try:
            rollback = dict(config)
            rollback["instance_storage_root"] = str(source_root)
            _write_config(rollback)
            config["instance_storage_root"] = str(source_root)
            for instance_id, record in originals.items():
                instance_runtime.register_instance(record)
                try:
                    materialize(config, record)
                except Exception:
                    pass
        except Exception:
            pass
        result = {
            "migration_id": migration_id,
            "status": "failed",
            "source_root": str(source_root),
            "target_root": str(target_root),
            "copied_instances": copied,
            "source_preserved": True,
            "error": str(exc)[:2000],
        }
        _atomic_json(RESULT_PATH, result)
        return result


__all__ = ["clear_result", "handle_command", "read_result"]