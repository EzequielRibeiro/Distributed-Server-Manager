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
from game_uptime_transaction_binding import BINDING_PATH

_ID = re.compile(r"[0-9a-f]{32}\Z")
_AGENT_ID = re.compile(r"[A-Za-z0-9._-]{1,191}\Z")


class HoldPreparationBlocked(RuntimeError):
    """Operator recovery is required; never retry by deleting evidence."""


def _trusted_directory(path: Path, uid: int, *,
                       runtime_readable: bool = False) -> None:
    """Refuse writable, symlinked or foreign storage, including its parent.

    An Agent/Worker may use a distinct UID and GID. The *ephemeral hold*
    directory and its ancestors must therefore be traversable by others;
    this never applies to the private persistent journal directory.
    """
    for candidate in (path.parent, path):
        info = candidate.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or (runtime_readable and not info.st_mode & stat.S_IXOTH)):
            raise HoldPreparationBlocked("untrusted_maintenance_storage")


def _write_once(path: Path, payload: dict[str, object], uid: int,
                *, mode: int = 0o600, max_bytes: int = 2048) -> None:
    """Exclusive create + fsync; partial evidence remains fail-closed.

    The journal must stay 0600. Only the non-secret ephemeral hold uses 0644:
    unprivileged Agents/Workers must read it but can never write it.
    """
    if mode not in (0o600, 0o644):
        raise HoldPreparationBlocked("invalid_evidence_mode")
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")
    if len(data) > max_bytes:
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
            # Creation always starts private; widen only after content is
            # written so no unprivileged reader observes partial JSON.
            raise HoldPreparationBlocked("untrusted_created_evidence")
        remaining = memoryview(data)
        while remaining:
            sent = os.write(fd, remaining)
            if sent <= 0:
                raise OSError("short journal write")
            remaining = remaining[sent:]
        if mode != 0o600:
            os.fchmod(fd, mode)
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
    release_sha256: str | None = None,
    binding_path: Path = BINDING_PATH,
    expected_agent_ids: list[str] | None = None,
) -> dict[str, object]:
    """Prepare a single pending transaction, with no implicit activation.

    The persistent pending record is fsynced BEFORE the ephemeral /run hold.
    A crash at any point leaves a journal that blocks reconciliation when
    the marker is missing. There is deliberately no cleanup API here.

    Injectable paths/uid are for disposable local tests only; installed
    callers must use the root-owned fixed paths and run as root.
    """
    journal_path, hold_path, binding_path = (
        Path(journal_path), Path(hold_path), Path(binding_path))
    if (os.geteuid() != trusted_uid or not journal_path.is_absolute()
            or not hold_path.is_absolute() or journal_path == hold_path):
        raise HoldPreparationBlocked("root_only_evidence_required")
    if type(transaction_id) is not str or not _ID.fullmatch(transaction_id):
        raise HoldPreparationBlocked("invalid_transaction_id")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
        raise HoldPreparationBlocked("invalid_lease_window")
    if release_sha256 is not None:
        if (type(release_sha256) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", release_sha256)
                or binding_path != journal_path.parent / "no-drain-release-binding.json"
                or not binding_path.is_absolute()
                or binding_path in (journal_path, hold_path)):
            raise HoldPreparationBlocked("invalid_release_binding_scope")
    inventory_path = journal_path.parent / "no-drain-agent-inventory.json"
    if expected_agent_ids is not None:
        if (release_sha256 is None or type(expected_agent_ids) is not list
                or not 1 <= len(expected_agent_ids) <= 64
                or any(type(agent) is not str or not _AGENT_ID.fullmatch(agent)
                       for agent in expected_agent_ids)
                or len(set(expected_agent_ids)) != len(expected_agent_ids)
                or inventory_path in (journal_path, hold_path, binding_path)):
            raise HoldPreparationBlocked("invalid_operator_agent_inventory")
        # Copy once; the inventory is supplied by the trusted coordinator,
        # never obtained from a single Agent or its heartbeat receipt.
        expected_agent_ids = sorted(expected_agent_ids)
    started = int(time.time()) if now is None else now
    if type(started) is not int or started <= 0:
        raise HoldPreparationBlocked("invalid_issue_time")

    # No path may be installed under an untrusted directory. Do not create
    # directories, replace files, follow links, unlink or overwrite evidence.
    try:
        _trusted_directory(journal_path.parent, trusted_uid)
        _trusted_directory(hold_path.parent, trusted_uid, runtime_readable=True)
        if release_sha256 is not None:
            _trusted_directory(binding_path.parent, trusted_uid)
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
        # Refuse an existing scope before creating any new evidence. O_EXCL
        # below is still authoritative if a competing root writer races us.
        paths = [journal_path, hold_path]
        if release_sha256 is not None:
            paths.extend((binding_path, inventory_path))
        for evidence in paths:
            try:
                evidence.lstat()
            except FileNotFoundError:
                continue
            raise HoldPreparationBlocked("existing_evidence_requires_review")
        # Persist the recovery sentinel FIRST. A crash during either
        # subsequent scope write must block even without the /run marker.
        _write_once(journal_path, pending, trusted_uid)
        if release_sha256 is not None:
            # Bind operator-pinned release bytes before hold exposure.
            # This SHA is NOT a publisher signature or an update approval.
            _write_once(binding_path, {
                "kind": "CapivaraDSMNoDrainReleaseBinding",
                "schema_version": 1,
                "transaction_id": transaction_id,
                "release_sha256": release_sha256,
                "issued_at": started,
                "expires_at": expires,
                "scope": "root_pinned_release_identity_only",
                "live_no_drain_authorized": False,
            }, trusted_uid, mode=0o644)
        if expected_agent_ids is not None:
            _write_once(inventory_path, {
                "kind": "DSM928OperatorAgentInventory",
                "schema_version": 1,
                "transaction_id": transaction_id,
                "release_sha256": release_sha256,
                "issued_at": started,
                "expires_at": expires,
                "agent_ids": expected_agent_ids,
            }, trusted_uid, max_bytes=16384)
        _write_once(hold_path, marker, trusted_uid, mode=0o644)
    except OSError as exc:
        raise HoldPreparationBlocked("evidence_write_failed_manual_recovery") from exc
    return {
        "status": "persistent_hold_prepared_manual_recovery_required",
        "transaction_id": transaction_id,
        "release_identity_bound_locally": release_sha256 is not None,
        "operator_agent_inventory_persisted": expected_agent_ids is not None,
        "publisher_signature_verified": False,
        "remote_agents_acked": False,
        "controller_http_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }
