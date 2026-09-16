#!/usr/bin/env python3
"""Agent-owned transaction boundary for M5 shared game-data maintenance.

The Controller may only round-trip an opaque transaction id. Filesystem paths,
provider metadata snapshots and rollback trees never leave the Agent.
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable

import instance_runtime
from backup_client import _create as create_backup
from server_update_agent import _affected, _context, _ensure_staging_space, _provider_metadata_snapshot
from server_update_provider import detect_update
from server_update_transaction import activate, cleanup_staging, commit, prepare_staging, restore_files, rollback

STATE_ROOT = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
TRANSACTION_ROOT = STATE_ROOT / "server-update-maintenance"
_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")


class MaintenanceGameUpdateError(RuntimeError):
    pass


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise MaintenanceGameUpdateError(f"invalid {label}")
    return text


def _path(transaction_id: str) -> Path:
    return TRANSACTION_ROOT / f"{_token(transaction_id, 'transaction_id')}.json"


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _encode_snapshot(snapshot: dict[str, tuple[bool, bytes | None, int | None]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, (existed, data, mode) in snapshot.items():
        result[str(name)] = {
            "existed": bool(existed),
            "data": base64.b64encode(data or b"").decode("ascii") if existed else None,
            "mode": int(mode) if mode is not None else None,
        }
    return result


def _decode_snapshot(raw: Any) -> dict[str, tuple[bool, bytes | None, int | None]]:
    if not isinstance(raw, dict):
        raise MaintenanceGameUpdateError("invalid provider metadata checkpoint")
    result: dict[str, tuple[bool, bytes | None, int | None]] = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            raise MaintenanceGameUpdateError("invalid provider metadata checkpoint entry")
        existed = bool(item.get("existed"))
        data = None
        if existed:
            try:
                data = base64.b64decode(str(item.get("data") or ""), validate=True)
            except Exception as exc:
                raise MaintenanceGameUpdateError("invalid provider metadata checkpoint payload") from exc
        mode = item.get("mode")
        result[str(name)] = (existed, data, int(mode) if mode is not None else None)
    return result


def _all_stopped(config: dict[str, Any], instance_ids: list[str]) -> None:
    unsafe: list[str] = []
    for instance_id in instance_ids:
        try:
            state = str(instance_runtime.status(config, instance_id).get("observed_state") or "unknown").lower()
        except Exception:
            state = "unknown"
        if state != "stopped":
            unsafe.append(f"{instance_id}:{state}")
    if unsafe:
        raise MaintenanceGameUpdateError(
            "shared game-data maintenance requires every affected instance stopped: " + ",".join(unsafe)
        )


def _load(selection: dict[str, Any], transaction_id: str) -> tuple[dict[str, Any], Path]:
    path = _path(transaction_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MaintenanceGameUpdateError("maintenance game update transaction not found") from exc
    except (OSError, ValueError) as exc:
        raise MaintenanceGameUpdateError("maintenance game update transaction is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("kind") != "CapivaraMaintenanceGameUpdateTransaction":
        raise MaintenanceGameUpdateError("invalid maintenance game update transaction")
    instance_id, record = _context(selection)
    if str(payload.get("instance_id") or "") != instance_id:
        raise MaintenanceGameUpdateError("maintenance transaction belongs to another instance")
    if str(payload.get("agent_id") or "") != str(record.get("agent_id") or ""):
        raise MaintenanceGameUpdateError("maintenance transaction belongs to another Agent")
    if str(payload.get("game_id") or "") != str(record.get("game_id") or ""):
        raise MaintenanceGameUpdateError("maintenance transaction belongs to another game")
    return payload, path


def prepare(
    selection: dict[str, Any],
    target: Path,
    installer: Callable[[Path], None],
    steamcmd: str | None = None,
) -> dict[str, Any]:
    """Activate a validated update while every shared-game instance is stopped.

    The previous tree remains available until ``finalize`` is called after M5
    readiness. Any failure before checkpoint persistence is rolled back locally.
    """
    instance_id, record = _context(selection)
    config = {"agent_id": str(record.get("agent_id") or "")}
    game = str(record.get("game_id") or "")
    affected = _affected(config, game)
    _all_stopped(config, affected)
    target = Path(target).resolve()
    before = detect_update(selection, target, steamcmd)
    if before.get("state") == "up_to_date":
        return {
            "changed": False,
            "transaction_id": None,
            "affected_instances": affected,
            "update_status_before": before,
            "update_status_after": before,
        }

    staging: Path | None = None
    previous: Path | None = None
    activated = False
    provider_snapshot: dict[str, tuple[bool, bytes | None, int | None]] = {}
    backups: list[dict[str, Any]] = []
    meta = selection.get("_server_update") if isinstance(selection.get("_server_update"), dict) else {}
    try:
        _ensure_staging_space(target)
        provider_snapshot = _provider_metadata_snapshot(selection, target)
        staging = prepare_staging(target)
        installer(staging)
        staged = detect_update(selection, staging, steamcmd, force_refresh=True)
        if staged.get("detector_supported") and staged.get("state") != "up_to_date":
            raise MaintenanceGameUpdateError("staged server version validation failed")
        if bool(meta.get("backup_before_update", True)):
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
            raise MaintenanceGameUpdateError("activated server version validation failed")
        transaction_id = "game-update-" + uuid.uuid4().hex
        checkpoint = {
            "schema_version": 1,
            "kind": "CapivaraMaintenanceGameUpdateTransaction",
            "transaction_id": transaction_id,
            "state": "prepared",
            "instance_id": instance_id,
            "agent_id": str(record.get("agent_id") or ""),
            "game_id": game,
            "target": str(target),
            "previous": str(previous) if previous is not None else None,
            "provider_snapshot": _encode_snapshot(provider_snapshot),
            "affected_instances": affected,
        }
        _write(_path(transaction_id), checkpoint)
        return {
            "changed": True,
            "transaction_id": transaction_id,
            "affected_instances": affected,
            "backups": backups,
            "update_status_before": before,
            "update_status_after": after,
            "rollback_supported": True,
        }
    except Exception:
        try:
            if activated:
                rollback(target, previous)
            restore_files(provider_snapshot)
        finally:
            cleanup_staging(staging)
        raise


def finalize(selection: dict[str, Any], transaction_id: str) -> dict[str, Any]:
    checkpoint, path = _load(selection, transaction_id)
    if str(checkpoint.get("state") or "") != "prepared":
        raise MaintenanceGameUpdateError("maintenance transaction is not prepared")
    previous = Path(str(checkpoint["previous"])).resolve() if checkpoint.get("previous") else None
    commit(previous)
    checkpoint["state"] = "committed"
    _write(path, checkpoint)
    path.unlink(missing_ok=True)
    return {"transaction_id": transaction_id, "state": "committed", "changed": True}


def rollback_transaction(selection: dict[str, Any], transaction_id: str) -> dict[str, Any]:
    checkpoint, path = _load(selection, transaction_id)
    if str(checkpoint.get("state") or "") != "prepared":
        raise MaintenanceGameUpdateError("maintenance transaction is not prepared")
    instance_id, record = _context(selection)
    config = {"agent_id": str(record.get("agent_id") or "")}
    affected = [str(value) for value in checkpoint.get("affected_instances") or []]
    _all_stopped(config, affected)
    target = Path(str(checkpoint.get("target") or "")).resolve()
    previous = Path(str(checkpoint["previous"])).resolve() if checkpoint.get("previous") else None
    if not rollback(target, previous):
        raise MaintenanceGameUpdateError("maintenance rollback tree is unavailable")
    restore_files(_decode_snapshot(checkpoint.get("provider_snapshot")))
    checkpoint["state"] = "rolled_back"
    _write(path, checkpoint)
    path.unlink(missing_ok=True)
    return {"transaction_id": transaction_id, "state": "rolled_back", "changed": True, "instance_id": instance_id}


__all__ = ["MaintenanceGameUpdateError", "finalize", "prepare", "rollback_transaction"]
