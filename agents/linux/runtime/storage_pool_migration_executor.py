#!/usr/bin/env python3
"""Execute one per-instance Storage Pool migration on the owning Linux Agent."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import instance_runtime
import privileged_materialization
from runtime_events import emit_runtime_event
from runtime_limits import runtime_limits
from runtime_operations import runtime_operation
from storage_pool_migration_state import safe_id, write_json
from storage_pools import resolve_storage_pool

_ALLOWED_STOPPED_STATES = {"stopped", "offline", "unknown", "unavailable"}


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


def _result(path: Path, command: dict[str, Any], *, status: str, step: str, progress: int, **extra: Any) -> dict[str, Any]:
    payload = {
        "migration_id": command["migration_id"],
        "instance_id": command["instance_id"],
        "status": status,
        "current_step": step,
        "progress": progress,
        **extra,
    }
    write_json(path, payload)
    return payload


def _event(config: dict[str, Any], command: dict[str, Any], event_type: str, *, step: str, progress: int,
           data: dict[str, Any] | None = None) -> None:
    emit_runtime_event(
        Path(instance_runtime.STATE_DIR),
        event_type,
        instance_id=command["instance_id"],
        agent_id=str(config.get("agent_id") or ""),
        data={
            "migration_id": command["migration_id"],
            "source_storage_pool_id": command["source_storage_pool_id"],
            "target_storage_pool_id": command["target_storage_pool_id"],
            "step": step,
            "progress": progress,
            **dict(data or {}),
        },
    )


def validate_command(config: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(command, dict):
        raise ValueError("storage pool migration command must be an object")
    normalized = dict(command)
    normalized["migration_id"] = safe_id(command.get("migration_id"), "migration_id")
    normalized["instance_id"] = safe_id(command.get("instance_id"), "instance_id")
    normalized["source_storage_pool_id"] = safe_id(command.get("source_storage_pool_id"), "source_storage_pool_id")
    normalized["target_storage_pool_id"] = safe_id(command.get("target_storage_pool_id"), "target_storage_pool_id")
    expected_agent = str(config.get("agent_id") or "").strip()
    claimed_agent = str(command.get("agent_id") or expected_agent).strip()
    if not expected_agent or claimed_agent != expected_agent:
        raise PermissionError("storage pool migration belongs to another Agent")
    normalized["agent_id"] = expected_agent
    if normalized["source_storage_pool_id"] == normalized["target_storage_pool_id"]:
        raise ValueError("source and target storage pools must differ")
    resolve_storage_pool(config, normalized["source_storage_pool_id"], require_enabled=False)
    resolve_storage_pool(config, normalized["target_storage_pool_id"], require_enabled=True)
    return normalized


def execute(config: dict[str, Any], command: dict[str, Any], result_path: Path) -> dict[str, Any]:
    command = validate_command(config, command)
    migration_id = command["migration_id"]
    instance_id = command["instance_id"]
    limits = runtime_limits(config)
    started = time.monotonic()
    original: dict[str, Any] | None = None
    copied: dict[str, Any] | None = None
    source_root: Path | None = None
    target_root: Path | None = None
    _result(result_path, command, status="running", step="staged", progress=1)
    _event(config, command, "INSTANCE_STORAGE_POOL_MIGRATION_STARTED", step="staged", progress=1)
    try:
        with runtime_operation(config, instance_id, "storage-pool-migrate", lock_timeout_seconds=limits.lock_timeout_seconds):
            original = dict(instance_runtime._owned(config, instance_id))
            current_pool = str(original.get("storage_pool_id") or "").strip()
            if current_pool != command["source_storage_pool_id"]:
                raise RuntimeError(
                    f"instance storage pool changed before migration: expected {command['source_storage_pool_id']}, found {current_pool or 'none'}"
                )
            status = instance_runtime.status(config, instance_id)
            observed = str(status.get("observed_state") or "unknown").strip().lower()
            if observed not in _ALLOWED_STOPPED_STATES:
                raise RuntimeError(f"instance must be stopped before storage pool migration: {instance_id} ({observed})")

            source_pool = resolve_storage_pool(config, command["source_storage_pool_id"], require_enabled=False)
            target_pool = resolve_storage_pool(config, command["target_storage_pool_id"], require_enabled=True)
            source_root = (Path(source_pool["root_path"]) / instance_id).resolve(strict=False)
            target_root = (Path(target_pool["root_path"]) / instance_id).resolve(strict=False)
            actual_root = Path(str(original.get("instance_state_root") or source_root)).resolve(strict=False)
            if actual_root != source_root:
                raise RuntimeError("instance state root does not match source Storage Pool")

            _result(result_path, command, status="running", step="copy_verify", progress=20)
            _event(config, command, "INSTANCE_STORAGE_POOL_MIGRATION_PROGRESS", step="copy_verify", progress=20)
            copied = privileged_materialization.migrate_storage_copy(
                config,
                original,
                target_storage_pool_id=command["target_storage_pool_id"],
                migration_id=migration_id,
            )
            _result(
                result_path, command, status="running", step="switch_runtime", progress=75,
                verified_files=int(copied.get("verified_files") or 0),
                verified_bytes=int(copied.get("verified_bytes") or 0),
            )
            _event(
                config, command, "INSTANCE_STORAGE_POOL_MIGRATION_PROGRESS", step="switch_runtime", progress=75,
                data={"verified_files": copied.get("verified_files"), "verified_bytes": copied.get("verified_bytes")},
            )

            updated = _replace_prefix(original, source_root, target_root)
            if not isinstance(updated, dict):
                raise RuntimeError("invalid migrated runtime specification")
            updated["storage_pool_id"] = command["target_storage_pool_id"]
            updated["instance_state_root"] = str(target_root)
            materialized = privileged_materialization.materialize(config, updated)
            instance_runtime.register_instance({**updated, "observed_state": "unknown", "materialized": True})

            final = _result(
                result_path,
                command,
                status="completed",
                step="completed",
                progress=100,
                source_preserved=True,
                target_committed=True,
                verified_files=int(copied.get("verified_files") or 0),
                verified_bytes=int(copied.get("verified_bytes") or 0),
                materialized_changed=bool((materialized.get("operation") or {}).get("changed")),
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            _event(
                config,
                command,
                "INSTANCE_STORAGE_POOL_MIGRATION_COMPLETED",
                step="completed",
                progress=100,
                data={
                    "verified_files": copied.get("verified_files"),
                    "verified_bytes": copied.get("verified_bytes"),
                    "source_preserved": True,
                },
            )
            return final
    except Exception as exc:
        rollback_error = None
        if original is not None:
            try:
                privileged_materialization.materialize(config, original)
                instance_runtime.register_instance(original)
            except Exception as rollback_exc:
                rollback_error = str(rollback_exc)[:1000]
        failed = _result(
            result_path,
            command,
            status="failed",
            step="failed",
            progress=100,
            error=str(exc)[:2000],
            rollback_error=rollback_error,
            source_preserved=True,
            target_committed=bool(copied and copied.get("atomic_commit")),
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        _event(
            config,
            command,
            "INSTANCE_STORAGE_POOL_MIGRATION_FAILED",
            step="failed",
            progress=100,
            data={"error": str(exc)[:2000], "rollback_error": rollback_error, "source_preserved": True},
        )
        return failed


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: storage_pool_migration_executor.py CONFIG REQUEST RESULT", file=sys.stderr)
        return 2
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    command = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    result = execute(config, command, Path(sys.argv[3]))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
