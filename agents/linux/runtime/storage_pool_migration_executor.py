#!/usr/bin/env python3
"""Execute per-instance Storage Pool migration and explicit source cleanup on the owning Linux Agent."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
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
            "source_migration_id": command.get("source_migration_id"),
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
    action = str(command.get("action") or "migrate").strip().lower()
    if action not in {"migrate", "cleanup-source"}:
        raise ValueError("invalid storage pool operation action")
    normalized["action"] = action
    normalized["migration_id"] = safe_id(command.get("migration_id"), "migration_id")
    normalized["instance_id"] = safe_id(command.get("instance_id"), "instance_id")
    normalized["source_storage_pool_id"] = safe_id(command.get("source_storage_pool_id"), "source_storage_pool_id")
    normalized["target_storage_pool_id"] = safe_id(command.get("target_storage_pool_id"), "target_storage_pool_id")
    if action == "cleanup-source":
        normalized["source_migration_id"] = safe_id(command.get("source_migration_id"), "source_migration_id")
    expected_agent = str(config.get("agent_id") or "").strip()
    claimed_agent = str(command.get("agent_id") or expected_agent).strip()
    if not expected_agent or claimed_agent != expected_agent:
        raise PermissionError("storage pool operation belongs to another Agent")
    normalized["agent_id"] = expected_agent
    if normalized["source_storage_pool_id"] == normalized["target_storage_pool_id"]:
        raise ValueError("source and target storage pools must differ")
    resolve_storage_pool(config, normalized["source_storage_pool_id"], require_enabled=False)
    resolve_storage_pool(config, normalized["target_storage_pool_id"], require_enabled=True)
    return normalized


def _tree_stats_without_links(root: Path) -> tuple[int, int]:
    files = 0
    total = 0
    if root.is_symlink():
        raise RuntimeError("refusing cleanup of symlinked source root")
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in list(dirs):
            child = current_path / name
            if child.is_symlink():
                raise RuntimeError(f"refusing cleanup because source contains symlink: {child.relative_to(root)}")
        for name in names:
            child = current_path / name
            if child.is_symlink():
                raise RuntimeError(f"refusing cleanup because source contains symlink: {child.relative_to(root)}")
            try:
                stat = child.stat()
            except OSError as exc:
                raise RuntimeError(f"cannot inspect cleanup source: {child.relative_to(root)}") from exc
            if child.is_file():
                files += 1
                total += int(stat.st_size)
    return files, total


def _execute_cleanup(config: dict[str, Any], command: dict[str, Any], result_path: Path) -> dict[str, Any]:
    command = validate_command(config, command)
    instance_id = command["instance_id"]
    limits = runtime_limits(config)
    started = time.monotonic()
    _result(result_path, command, status="running", step="validate", progress=1)
    _event(config, command, "INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_STARTED", step="validate", progress=1)
    try:
        with runtime_operation(config, instance_id, "storage-pool-source-cleanup", lock_timeout_seconds=limits.lock_timeout_seconds):
            current = dict(instance_runtime._owned(config, instance_id))
            current_pool = str(current.get("storage_pool_id") or "").strip()
            if current_pool != command["target_storage_pool_id"]:
                raise RuntimeError(
                    f"instance is not assigned to cleanup target Storage Pool: expected {command['target_storage_pool_id']}, found {current_pool or 'none'}"
                )
            source_pool = resolve_storage_pool(config, command["source_storage_pool_id"], require_enabled=False)
            target_pool = resolve_storage_pool(config, command["target_storage_pool_id"], require_enabled=True)
            source_parent = Path(source_pool["root_path"]).resolve(strict=False)
            target_parent = Path(target_pool["root_path"]).resolve(strict=False)
            source_root = (source_parent / instance_id).resolve(strict=False)
            target_root = (target_parent / instance_id).resolve(strict=False)
            actual_root = Path(str(current.get("instance_state_root") or target_root)).resolve(strict=False)
            if actual_root != target_root:
                raise RuntimeError("instance state root does not match cleanup target Storage Pool")
            if source_root == target_root or source_root.parent != source_parent or target_root.parent != target_parent:
                raise RuntimeError("unsafe Storage Pool cleanup path resolution")
            if source_root == Path("/") or source_parent == Path("/"):
                raise RuntimeError("refusing unsafe Storage Pool cleanup root")

            _result(result_path, command, status="running", step="inspect-source", progress=30)
            _event(config, command, "INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_PROGRESS", step="inspect-source", progress=30)
            if not source_root.exists():
                final = _result(
                    result_path, command, status="completed", step="completed", progress=100,
                    already_absent=True, removed_files=0, removed_bytes=0,
                    source_storage_pool_id=command["source_storage_pool_id"],
                    target_storage_pool_id=command["target_storage_pool_id"],
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
                _event(config, command, "INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_COMPLETED", step="completed", progress=100,
                       data={"already_absent": True, "removed_files": 0, "removed_bytes": 0})
                return final
            if not source_root.is_dir():
                raise RuntimeError("cleanup source is not a directory")
            files, total = _tree_stats_without_links(source_root)
            expected_files = command.get("expected_verified_files")
            expected_bytes = command.get("expected_verified_bytes")
            if expected_files is not None and int(expected_files) != files:
                raise RuntimeError("cleanup source file count changed since migration verification")
            if expected_bytes is not None and int(expected_bytes) != total:
                raise RuntimeError("cleanup source byte count changed since migration verification")

            _result(result_path, command, status="running", step="remove-source", progress=75,
                    inspected_files=files, inspected_bytes=total)
            _event(config, command, "INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_PROGRESS", step="remove-source", progress=75,
                   data={"inspected_files": files, "inspected_bytes": total})
            shutil.rmtree(source_root)
            if source_root.exists():
                raise RuntimeError("cleanup source still exists after removal")
            final = _result(
                result_path, command, status="completed", step="completed", progress=100,
                already_absent=False, removed_files=files, removed_bytes=total,
                source_storage_pool_id=command["source_storage_pool_id"],
                target_storage_pool_id=command["target_storage_pool_id"],
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            _event(config, command, "INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_COMPLETED", step="completed", progress=100,
                   data={"removed_files": files, "removed_bytes": total})
            return final
    except Exception as exc:
        failed = _result(
            result_path, command, status="failed", step="failed", progress=100,
            error=str(exc)[:2000], source_preserved=True,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        _event(config, command, "INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_FAILED", step="failed", progress=100,
               data={"error": str(exc)[:2000], "source_preserved": True})
        return failed


def execute(config: dict[str, Any], command: dict[str, Any], result_path: Path) -> dict[str, Any]:
    command = validate_command(config, command)
    if command["action"] == "cleanup-source":
        return _execute_cleanup(config, command, result_path)
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
            copied = privileged_materialization.migrate_storage_pool_copy(
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
