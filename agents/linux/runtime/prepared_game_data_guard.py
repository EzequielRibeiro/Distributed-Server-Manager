#!/usr/bin/env python3
"""Prevent overlapping prepared DayZ maintenance and server updates (#977).

Call only while holding the installation's game_data_update_lock. This guard
does not acquire that lock and is not a replacement for transaction identity.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path


class PreparedGameDataTransactionError(RuntimeError):
    pass


MAX_CHECKPOINTS = 4096
MAX_CHECKPOINT_BYTES = 1024 * 1024


def reject_prepared_dayz_transaction(
    target: Path, *, transaction_root: Path | None = None,
) -> None:
    """Fail closed when a prepared DayZ checkpoint references this installation.

    Unknown/malformed checkpoints fail closed (rather than risk overwriting the
    rollback baseline), even if their intended target cannot be determined.
    """
    root = Path(transaction_root) if transaction_root is not None else (
        Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
        / "server-update-maintenance"
    )
    target = Path(target).resolve(strict=True)
    if not root.exists():
        return
    if root.is_symlink() or not root.is_dir():
        raise PreparedGameDataTransactionError("unsafe_maintenance_checkpoint_root")
    try:
        entries = list(root.iterdir())
        if len(entries) > MAX_CHECKPOINTS:
            raise PreparedGameDataTransactionError("too_many_maintenance_checkpoints")
        for entry in entries:
            if not entry.name.endswith(".json") or entry.name.startswith("."):
                continue
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PreparedGameDataTransactionError("unsafe_maintenance_checkpoint")
            if info.st_size > MAX_CHECKPOINT_BYTES:
                raise PreparedGameDataTransactionError("oversized_maintenance_checkpoint")
            try:
                payload = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError) as exc:
                raise PreparedGameDataTransactionError("invalid_maintenance_checkpoint") from exc
            if not isinstance(payload, dict) or payload.get("kind") != "CapivaraMaintenanceGameUpdateTransaction":
                raise PreparedGameDataTransactionError("invalid_maintenance_checkpoint")
            if payload.get("state") != "prepared" or payload.get("game_id") != "dayz":
                continue
            stored = payload.get("target")
            if not isinstance(stored, str) or not Path(stored).is_absolute():
                raise PreparedGameDataTransactionError("invalid_prepared_installation")
            if Path(stored).resolve(strict=False) == target:
                raise PreparedGameDataTransactionError("prepared_dayz_transaction_pending")
    except PreparedGameDataTransactionError:
        raise
    except OSError as exc:
        raise PreparedGameDataTransactionError("maintenance_checkpoint_scan_failed") from exc


__all__ = ["PreparedGameDataTransactionError", "reject_prepared_dayz_transaction"]
