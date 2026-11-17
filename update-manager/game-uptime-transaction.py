#!/usr/bin/env python3
"""Experimental *disposable-only* uptime transaction checkpoint for #928.

Not wired to update.sh, not a production update mechanism, and never grants
live_no_drain_authorized. The caller supplies isolated apply/rollback callbacks
and snapshot inspection for disposable units; this module maintains a durable
fail-closed journal and verifies PID/start identity around both operations.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Callable, Mapping

_UNIT = re.compile(r"dsm928-e2e-[a-z0-9-]+\.service\Z")


class TransactionSafetyError(RuntimeError):
    pass


def _workspace(parent: Path) -> Path:
    root = Path(parent)
    if root.is_symlink() or not root.is_dir():
        raise TransactionSafetyError("disposable workspace must be an existing non-symlink directory")
    resolved = root.resolve(strict=True)
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    if resolved == temp_root or temp_root not in resolved.parents:
        raise TransactionSafetyError("disposable transaction must run inside a temporary sandbox")
    # The fsynced rollback journal contains process identities and is trusted
    # for manual crash recovery. Never accept group/other writable or readable
    # journal directories, even when they are beneath /tmp. The disposable
    # operator must own the directory, so other host users cannot replace it.
    identity = resolved.stat()
    if identity.st_uid != os.geteuid() or identity.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise TransactionSafetyError("disposable journal directory must be private and owned")
    return resolved


def _snapshot(name: str, inspect: Callable[[str], Mapping]) -> dict:
    try:
        state = inspect(name)
        if not isinstance(state, Mapping) or state.get("unit") != name:
            raise ValueError("unit identity mismatch")
        pid = state.get("pid")
        started = state.get("started")
        if type(pid) is not int or pid < 2 or type(started) is not int or started <= 0:
            raise ValueError("invalid PID or monotonic start timestamp")
        if state.get("state") != "active":
            raise ValueError("disposable unit not active")
        return {"unit": name, "pid": pid, "started": started, "state": "active"}
    except Exception as exc:
        raise TransactionSafetyError(f"cannot prove disposable unit identity: {name}") from exc


def _checkpoint(path: Path, status: str, originals: list[dict], detail: str = "") -> None:
    report = {
        "kind": "DSM928DisposableUptimeTransaction",
        "scope": "disposable_only_not_production",
        "status": status,
        "live_no_drain_authorized": False,
        "original_units": originals,
        "detail": detail[:300],
    }
    tmp = path.with_name("." + path.name + ".part")
    # No following a stale staging symlink; never overwrite a previous journal.
    if tmp.exists() or tmp.is_symlink():
        raise TransactionSafetyError("stale transaction journal staging file")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if tmp.exists():
            tmp.unlink()


def execute(
    workspace: Path,
    units: list[str],
    *,
    inspect: Callable[[str], Mapping],
    apply: Callable[[], None],
    rollback: Callable[[], None],
) -> dict:
    """Run one isolated transaction. Fail closed after any interrupted run.

    On a caught apply/check failure, attempt rollback and re-verify PIDs.
    On SIGKILL/SystemExit, the nonterminal journal remains; manual recovery
    is required and automatic replay is intentionally prohibited.
    """
    root = _workspace(workspace)
    if (not isinstance(units, list) or not units
            or any(not isinstance(unit, str) or not _UNIT.fullmatch(unit) for unit in units)
            or len(units) != len(set(units))):
        raise TransactionSafetyError("only named disposable E2E systemd units are allowed")
    path = root / "game-uptime-transaction.json"
    if path.exists() or path.is_symlink():
        raise TransactionSafetyError("existing transaction evidence requires manual review")
    before = [_snapshot(unit, inspect) for unit in sorted(units)]
    _checkpoint(path, "prepared", before)
    try:
        apply()
        _checkpoint(path, "applied", before)
        after = [_snapshot(row["unit"], inspect) for row in before]
        if after != before:
            raise TransactionSafetyError("PID or start identity changed during apply")
        _checkpoint(path, "verified", before)
        return {"status": "verified", "live_no_drain_authorized": False, "units": after}
    except Exception as exc:
        try:
            rollback()
            after_rollback = [_snapshot(row["unit"], inspect) for row in before]
            if after_rollback != before:
                raise TransactionSafetyError("PID or start identity changed during rollback")
            _checkpoint(path, "rolled_back", before, str(exc))
        except Exception as rollback_exc:
            _checkpoint(path, "manual_recovery_required", before, str(rollback_exc))
            raise TransactionSafetyError("rollback failed; manual recovery required") from rollback_exc
        raise TransactionSafetyError("transaction rejected and rollback completed") from exc

def recover_interrupted(
    workspace: Path,
    units: list[str],
    *,
    inspect: Callable[[str], Mapping],
    rollback: Callable[[], None],
    operator_reviewed: bool = False,
) -> dict:
    """Explicit, disposable-only rollback of one interrupted transaction.

    Not automatic startup recovery: the operator must review journal and
    externally verify the appropriate rollback callback before opting in.
    A process crash *during* this recovery remains manual-only, not replayed.
    """
    root = _workspace(workspace)
    if operator_reviewed is not True:
        raise TransactionSafetyError("explicit operator review is required")
    if (not isinstance(units, list) or not units
            or any(not isinstance(unit, str) or not _UNIT.fullmatch(unit)
                   for unit in units)
            or len(units) != len(set(units))):
        raise TransactionSafetyError("only named disposable E2E systemd units are allowed")
    path = root / "game-uptime-transaction.json"
    if path.is_symlink() or not path.is_file():
        raise TransactionSafetyError("missing or unsafe transaction journal")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized journal")
        report = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise TransactionSafetyError("unreadable transaction journal") from exc
    if (not isinstance(report, dict)
            or report.get("kind") != "DSM928DisposableUptimeTransaction"
            or report.get("scope") != "disposable_only_not_production"
            or report.get("live_no_drain_authorized") is not False
            or report.get("status") not in {"prepared", "applied"}
            or not isinstance(report.get("original_units"), list)):
        raise TransactionSafetyError("journal does not prove recoverable interruption")
    recorded = report["original_units"]
    if len(recorded) != len(units) or any(
            not isinstance(item, dict)
            for item in recorded):
        raise TransactionSafetyError("journal inventory mismatch")
    # The journal must match the *same* processes by unit, PID and start stamp.
    # Never invoke rollback if an observed unit was replaced while we were down.
    actual = [_snapshot(name, inspect) for name in sorted(units)]
    if recorded != actual:
        raise TransactionSafetyError("process identity changed; manual recovery required")
    _checkpoint(path, "recovery_started", actual,
                "explicit disposable-only recovery")
    try:
        rollback()
        after = [_snapshot(name, inspect) for name in sorted(units)]
        if after != actual:
            raise TransactionSafetyError("process changed during recovery rollback")
        _checkpoint(path, "recovered_rollback", actual)
        return {"status": "recovered_rollback",
                "live_no_drain_authorized": False, "units": after}
    except Exception as exc:
        _checkpoint(path, "manual_recovery_required", actual, str(exc))
        raise TransactionSafetyError("recovery rollback failed; manual review required") from exc
