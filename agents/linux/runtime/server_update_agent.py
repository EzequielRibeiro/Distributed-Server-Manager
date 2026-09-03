#!/usr/bin/env python3
"""Safe Agent-side orchestration for shared game-server updates."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

import instance_runtime
from backup_client import _create as create_backup
from server_update_provider import _manifest_candidates, detect_update
from server_update_transaction import activate, cleanup_staging, commit, prepare_staging, restore_files, rollback, snapshot_files


class ServerUpdateError(RuntimeError):
    code = "update_failed"


class VersionValidationError(ServerUpdateError):
    code = "version_validation_failed"


class ReadinessValidationError(ServerUpdateError):
    code = "readiness_failed"


class RollbackError(ServerUpdateError):
    code = "rollback_failed"


def _context(selection: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    meta = selection.get("_server_update") if isinstance(selection.get("_server_update"), dict) else {}
    iid = str(meta.get("instance_id") or "").strip()
    if not iid:
        raise ValueError("server update instance_id is required")
    record = instance_runtime.get_instance(iid)
    if not record:
        raise LookupError("server update instance not found")
    game = str(selection.get("game") or record.get("game_id") or "").strip()
    if not game or game != str(record.get("game_id") or ""):
        raise ValueError("server update game identity mismatch")
    return iid, record


def _affected(config: dict[str, Any], game: str) -> list[str]:
    return [str(item["instance_id"]) for item in instance_runtime.list_instances(config) if str(item.get("game_id") or "") == game]


def _tree_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _ensure_staging_space(target: Path) -> None:
    required = _tree_size(target)
    if required <= 0:
        return
    free = shutil.disk_usage(target.parent).free
    # copytree creates a full local last-known-good candidate, so reserve headroom.
    if free < required + max(256 * 1024 * 1024, required // 20):
        raise ServerUpdateError("insufficient free space for transactional game-data staging")


def _provider_metadata_snapshot(selection: dict[str, Any], target: Path) -> dict[str, tuple[bool, bytes | None, int | None]]:
    if str(selection.get("provider") or "").strip().lower() != "steam":
        return {}
    install = selection.get("install") if isinstance(selection.get("install"), dict) else {}
    appid = str(install.get("package_id") or "").strip()
    if not appid.isdigit():
        return {}
    return snapshot_files(_manifest_candidates(target, appid))


def _stop_running(config: dict[str, Any], instance_ids: list[str]) -> None:
    for current in instance_ids:
        try:
            if instance_runtime.status(config, current).get("observed_state") == "running":
                instance_runtime.lifecycle(config, current, "stop")
        except Exception:
            # Caller handles readiness/rollback outcome; continue best-effort shutdown.
            pass


def _restart_and_validate(config: dict[str, Any], instance_ids: list[str]) -> tuple[list[str], list[str]]:
    restarted: list[str] = []
    failures: list[str] = []
    for current in instance_ids:
        try:
            instance_runtime.lifecycle(config, current, "start")
            restarted.append(current)
            doctor = instance_runtime.doctor(config, current)
            if not doctor.get("ready"):
                failures.append(current)
        except Exception:
            failures.append(current)
    return restarted, failures


def perform_update(
    selection: dict[str, Any],
    target: Path,
    installer: Callable[[Path], None],
    steamcmd: str | None = None,
) -> dict[str, Any]:
    """Stage, validate, atomically activate and rollback shared game data when needed."""
    _, record = _context(selection)
    config = {"agent_id": str(record.get("agent_id") or "")}
    game = str(record.get("game_id") or "")
    meta = selection.get("_server_update") or {}
    backup_enabled = bool(meta.get("backup_before_update", True))
    affected = _affected(config, game)
    target = Path(target).resolve()
    running: list[str] = []
    backups: list[dict[str, Any]] = []
    restarted: list[str] = []
    staging: Path | None = None
    previous: Path | None = None
    activated = False
    provider_snapshot: dict[str, tuple[bool, bytes | None, int | None]] = {}

    before = detect_update(selection, target, steamcmd)
    if before.get("state") == "up_to_date":
        return {
            "update_status_before": before,
            "update_status_after": before,
            "affected_instances": affected,
            "backups": [],
            "restarted_instances": [],
            "readiness": "unchanged",
            "rollback_supported": True,
            "rollback_performed": False,
        }

    try:
        _ensure_staging_space(target)
        provider_snapshot = _provider_metadata_snapshot(selection, target)
        staging = prepare_staging(target)
        installer(staging)

        staged_status = detect_update(selection, staging, steamcmd, force_refresh=True)
        if staged_status.get("detector_supported") and staged_status.get("state") != "up_to_date":
            raise VersionValidationError("staged server version validation failed")

        for current in affected:
            if instance_runtime.status(config, current).get("observed_state") == "running":
                instance_runtime.lifecycle(config, current, "stop")
                running.append(current)

        if backup_enabled:
            for current in affected:
                detail = create_backup(
                    config,
                    {"instance_id": current, "policy": {"mode": "full", "compression": "gzip", "retention_count": 7, "consistency": "live"}},
                )
                backups.append({
                    "instance_id": current,
                    "backup_id": detail.get("backup_id"),
                    "sha256": detail.get("sha256"),
                    "size_bytes": detail.get("size_bytes"),
                })

        previous = activate(target, staging)
        staging = None
        activated = True

        after = detect_update(selection, target, steamcmd, force_refresh=True)
        if after.get("detector_supported") and after.get("state") != "up_to_date":
            raise VersionValidationError("activated server version validation failed")

        restarted, failures = _restart_and_validate(config, running)
        if failures:
            raise ReadinessValidationError("updated server failed readiness validation: " + ",".join(failures))

        commit(previous)
        previous = None
        return {
            "update_status_before": before,
            "update_status_after": after,
            "affected_instances": affected,
            "backups": backups,
            "restarted_instances": restarted,
            "readiness": "healthy",
            "rollback_supported": True,
            "rollback_performed": False,
            "activation": "atomic-swap",
        }
    except Exception as exc:
        rollback_error: Exception | None = None
        try:
            if activated:
                _stop_running(config, running)
                if not rollback(target, previous):
                    raise RollbackError("previous game-data tree is unavailable")
                previous = None
            restore_files(provider_snapshot)
            cleanup_staging(staging)
            staging = None
            _, recovery_failures = _restart_and_validate(config, running)
            if recovery_failures:
                raise RollbackError("rollback restored files but runtime recovery failed: " + ",".join(recovery_failures))
        except Exception as recovery_exc:
            rollback_error = recovery_exc
        finally:
            cleanup_staging(staging)

        if rollback_error is not None:
            raise RollbackError(f"server update failed ({exc}); rollback failed ({rollback_error})") from exc
        raise ServerUpdateError(f"server update failed and rollback completed: {exc}") from exc


__all__ = [
    "ReadinessValidationError",
    "RollbackError",
    "ServerUpdateError",
    "VersionValidationError",
    "perform_update",
]
