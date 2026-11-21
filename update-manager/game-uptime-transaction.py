#!/usr/bin/env python3
"""Experimental *disposable-only* uptime transaction checkpoint for #928.

Not wired to update.sh, not a production update mechanism, and never grants
live_no_drain_authorized. The caller supplies isolated apply/rollback callbacks
and snapshot inspection for disposable units; this module maintains a durable
fail-closed journal and verifies PID/start identity around both operations.
"""
from __future__ import annotations

import json
import hashlib
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
        # The systemd unit witness is optional for older disposable fixtures,
        # but once supplied it becomes part of the durable original identity.
        # An omitted, malformed or changed witness after apply/rollback is
        # rejected as a process-preservation failure even if PID is unchanged.
        result = {"unit": name, "pid": pid, "started": started, "state": "active"}
        witness = state.get("unit_config_sha256")
        if witness is not None:
            if (not isinstance(witness, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", witness)):
                raise ValueError("invalid systemd unit configuration witness")
            result["unit_config_sha256"] = witness
        return result
    except Exception as exc:
        raise TransactionSafetyError(f"cannot prove disposable unit identity: {name}") from exc



def _active_set(units: list[str], list_units: Callable[[], list[str]]) -> None:
    """Verify ALL active disposable game units, not merely the known PIDs."""
    try:
        observed = list_units()
    except Exception as exc:
        raise TransactionSafetyError("complete game inventory unreadable") from exc
    if (not isinstance(observed, list)
            or any(not isinstance(x, str) or not _UNIT.fullmatch(x) for x in observed)
            or len(observed) != len(set(observed))
            or sorted(observed) != sorted(units)):
        raise TransactionSafetyError("complete active game unit set changed")


def attest_handoff(units: list[str], *, inspect: Callable[[str], Mapping],
                   list_units: Callable[[], list[str]]) -> dict:
    """Produce a read-only double-sampled witness for a disposable transaction."""
    if (not isinstance(units, list) or not units
            or any(not isinstance(x, str) or not _UNIT.fullmatch(x) for x in units)
            or len(units) != len(set(units))):
        raise TransactionSafetyError("only disposable E2E game units are allowed")
    _active_set(units, list_units)
    original = [_snapshot(x, inspect) for x in sorted(units)]
    if any("unit_config_sha256" not in x for x in original):
        raise TransactionSafetyError("full systemd unit digest is required")
    _active_set(units, list_units)
    if [_snapshot(x, inspect) for x in sorted(units)] != original:
        raise TransactionSafetyError("game identity changed during handoff")
    return {"kind": "DSM928DisposableInventoryHandoff",
            "scope": "disposable_only_not_production",
            "live_no_drain_authorized": False, "original_units": original}


def _check_handoff(expected: list[dict], handoff: Mapping) -> None:
    if (not isinstance(handoff, Mapping)
            or handoff.get("kind") != "DSM928DisposableInventoryHandoff"
            or handoff.get("scope") != "disposable_only_not_production"
            or handoff.get("live_no_drain_authorized") is not False
            or handoff.get("original_units") != expected
            or any("unit_config_sha256" not in x for x in expected)):
        raise TransactionSafetyError("preflight handoff no longer matches game processes")


def _digest(original: list[dict]) -> str:
    return hashlib.sha256(json.dumps(original, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()

def _checkpoint(path: Path, status: str, originals: list[dict], detail: str = "",
                strict_inventory: bool = False) -> None:
    report = {
        "kind": "DSM928DisposableUptimeTransaction",
        "scope": "disposable_only_not_production",
        "status": status,
        "live_no_drain_authorized": False,
        "original_units": originals,
        "original_units_sha256": _digest(originals),
        "strict_inventory": strict_inventory,
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
    handoff: Mapping | None = None,
    list_units: Callable[[], list[str]] | None = None,
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
    if (handoff is None) != (list_units is None):
        raise TransactionSafetyError("handoff and complete inventory callback must be paired")
    strict = handoff is not None
    path = root / "game-uptime-transaction.json"
    if path.exists() or path.is_symlink():
        raise TransactionSafetyError("existing transaction evidence requires manual review")
    if strict:
        _active_set(units, list_units)
    before = [_snapshot(x, inspect) for x in sorted(units)]
    if strict:
        _check_handoff(before, handoff)
        _active_set(units, list_units)
    _checkpoint(path, "prepared", before, strict_inventory=strict)
    if strict:
        try:
            _active_set(units, list_units)
            if [_snapshot(x, inspect) for x in sorted(units)] != before:
                raise TransactionSafetyError("process identity changed before apply")
        except TransactionSafetyError as exc:
            _checkpoint(path, "manual_recovery_required", before, str(exc),
                        strict_inventory=True)
            raise TransactionSafetyError("game handoff changed before apply; manual review required") from exc
    try:
        apply()
        _checkpoint(path, "applied", before, strict_inventory=strict)
        if strict:
            _active_set(units, list_units)
        after = [_snapshot(x["unit"], inspect) for x in before]
        if after != before:
            raise TransactionSafetyError("process or unit configuration changed during apply")
        _checkpoint(path, "verified", before, strict_inventory=strict)
        return {"status": "verified", "live_no_drain_authorized": False, "units": after}
    except Exception as exc:
        # Unknown/missing active units after apply must not cause a blind rollback.
        if strict:
            try:
                _active_set(units, list_units)
            except TransactionSafetyError as inventory_exc:
                _checkpoint(path, "manual_recovery_required", before,
                            str(inventory_exc), strict_inventory=True)
                raise TransactionSafetyError(
                    "game inventory changed after apply; manual recovery required") from exc
        try:
            rollback()
            if strict:
                _active_set(units, list_units)
            after_rollback = [_snapshot(x["unit"], inspect) for x in before]
            if after_rollback != before:
                raise TransactionSafetyError("process or unit configuration changed during rollback")
            _checkpoint(path, "rolled_back", before, str(exc), strict_inventory=strict)
        except Exception as rollback_exc:
            _checkpoint(path, "manual_recovery_required", before, str(rollback_exc),
                        strict_inventory=strict)
            raise TransactionSafetyError("rollback failed; manual recovery required") from rollback_exc
        raise TransactionSafetyError("transaction rejected and rollback completed") from exc


def recover_interrupted(
    workspace: Path,
    units: list[str],
    *,
    inspect: Callable[[str], Mapping],
    rollback: Callable[[], None],
    operator_reviewed: bool = False,
    list_units: Callable[[], list[str]] | None = None,
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
    if len(recorded) != len(units) or any(not isinstance(x, dict) for x in recorded):
        raise TransactionSafetyError("journal inventory mismatch")
    try:
        matches_digest = report.get("original_units_sha256") == _digest(recorded)
    except (ValueError, TypeError):
        matches_digest = False
    if not matches_digest:
        raise TransactionSafetyError("durable process witness digest mismatch")
    strict = report.get("strict_inventory") is True
    if strict != (list_units is not None):
        raise TransactionSafetyError("durable inventory witness callback missing or unexpected")
    if strict:
        _active_set(units, list_units)
    actual = [_snapshot(x, inspect) for x in sorted(units)]
    if recorded != actual:
        raise TransactionSafetyError(
            "process identity changed or unit configuration changed; manual recovery required")
    if strict:
        _active_set(units, list_units)
    _checkpoint(path, "recovery_started", actual,
                "explicit disposable-only recovery", strict_inventory=strict)
    try:
        if strict:
            _active_set(units, list_units)
        rollback()
        if strict:
            _active_set(units, list_units)
        after = [_snapshot(name, inspect) for name in sorted(units)]
        if after != actual:
            raise TransactionSafetyError("process or unit configuration changed during recovery rollback")
        _checkpoint(path, "recovered_rollback", actual, strict_inventory=strict)
        return {"status": "recovered_rollback",
                "live_no_drain_authorized": False, "units": after}
    except Exception as exc:
        _checkpoint(path, "manual_recovery_required", actual, str(exc),
                    strict_inventory=strict)
        raise TransactionSafetyError("recovery rollback failed; manual review required") from exc
