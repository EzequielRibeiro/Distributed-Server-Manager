#!/usr/bin/env python3
"""Root-only, fail-closed preparation of DSM #928 maintenance evidence.

Not connected to update.sh, Controller dispatch, Agent startup or systemd.
This is a *preparatory* transaction owner, never an approval to update live
games. An existing or partially written persistent journal MUST remain a
blocker after a crash, including if the /run marker is lost on reboot.

No automatic completion, lease renewal, removal or recovery is exposed.
Those operations require a later independently verified distributed fence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import time

from game_uptime_maintenance_hold import HOLD_PATH, PENDING_PATH

_ID = re.compile(r"[0-9a-f]{32}\Z")


class HoldPreparationBlocked(RuntimeError):
    """Operator recovery is required; never retry by deleting evidence."""


def _trusted_directory(path: Path, uid: int) -> None:
    """Refuse writable, symlinked or foreign storage, including its parent."""
    for candidate in (path.parent, path):
        info = candidate.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise HoldPreparationBlocked("untrusted_maintenance_storage")


def _write_once(path: Path, payload: dict[str, object], uid: int) -> None:
    """Exclusive create + fsync; a partial file is retained as fail-closed."""
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")
    if len(data) > 2048:
        raise HoldPreparationBlocked("evidence_too_large")
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise HoldPreparationBlocked("existing_evidence_requires_review") from exc
    # On any failure AFTER O_EXCL, leave the inode intact. The reader regards
    # its presence as a block even if the JSON or fsync was incomplete.
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1):
            raise HoldPreparationBlocked("untrusted_created_evidence")
        remaining = memoryview(data)
        while remaining:
            sent = os.write(fd, remaining)
            if sent <= 0:
                raise OSError("short journal write")
            remaining = remaining[sent:]
        os.fsync(fd)
    finally:
        os.close(fd)
    directory_fd = os.open(
        path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def prepare_root_only(
    *, transaction_id: str, ttl_seconds: int = 600,
    journal_path: Path = PENDING_PATH, hold_path: Path = HOLD_PATH,
    trusted_uid: int = 0, now: int | None = None,
) -> dict[str, object]:
    """Prepare a single pending transaction, with no implicit activation.

    The persistent pending record is fsynced BEFORE the ephemeral /run hold.
    A crash at any point leaves a journal that blocks reconciliation when
    the marker is missing. There is deliberately no cleanup API here.

    Injectable paths/uid are for disposable local tests only; installed
    callers must use the root-owned fixed paths and run as root.
    """
    journal_path, hold_path = Path(journal_path), Path(hold_path)
    if (os.geteuid() != trusted_uid or not journal_path.is_absolute()
            or not hold_path.is_absolute() or journal_path == hold_path):
        raise HoldPreparationBlocked("root_only_evidence_required")
    if type(transaction_id) is not str or not _ID.fullmatch(transaction_id):
        raise HoldPreparationBlocked("invalid_transaction_id")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
        raise HoldPreparationBlocked("invalid_lease_window")
    started = int(time.time()) if now is None else now
    if type(started) is not int or started <= 0:
        raise HoldPreparationBlocked("invalid_issue_time")

    # No path may be installed under an untrusted directory. Do not create
    # directories, replace files, follow links, unlink or overwrite evidence.
    try:
        _trusted_directory(journal_path.parent, trusted_uid)
        _trusted_directory(hold_path.parent, trusted_uid)
    except OSError as exc:
        raise HoldPreparationBlocked("evidence_directory_unavailable") from exc

    expires = started + ttl_seconds
    pending = {
        "kind": "CapivaraDSMNoDrainPendingJournal",
        "schema_version": 1,
        "transaction_id": transaction_id,
        "issued_at": started,
        "expires_at": expires,
        "state": "prepared_requires_distributed_fence",
        "live_no_drain_authorized": False,
    }
    marker = {
        "kind": "CapivaraDSMNoDrainMaintenanceHold",
        "schema_version": 1,
        "transaction_id": transaction_id,
        "issued_at": started,
        "expires_at": expires,
    }
    try:
        _write_once(journal_path, pending, trusted_uid)
        _write_once(hold_path, marker, trusted_uid)
    except OSError as exc:
        raise HoldPreparationBlocked("evidence_write_failed_manual_recovery") from exc
    return {
        "status": "persistent_hold_prepared_manual_recovery_required",
        "transaction_id": transaction_id,
        "remote_agents_acked": False,
        "controller_http_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }
