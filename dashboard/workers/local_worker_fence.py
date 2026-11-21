#!/usr/bin/env python3
"""Phase-2 local exclusive Worker fence for DSM #928; NOT a release gate.

Safely hold all nine existing root-provisioned flock inodes at once while a
valid root-owned transaction hold is present. Identity validation and the
exclusive locks apply ONLY to tracked local Worker cycles. They do not prove
that dispatched jobs, privileged helpers, HTTP handlers or remote Agents
are quiescent. No live no-drain update is authorized by this module.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import fcntl
from pathlib import Path
import re
from typing import Iterator

from game_uptime_maintenance_hold import observe
from maintenance_hold_gate import _KNOWN_WORKERS, _directory, _open_lock
from worker_identity_diagnostic import inspect as inspect_worker_identity

_TRANSACTION = re.compile(r"[0-9a-f]{32}\Z")


class LocalFenceUnavailable(RuntimeError):
    """Fail-closed evidence error; not a signal to retry a live update."""


def _identity(hold: object) -> tuple[str, int, int]:
    if not isinstance(hold, dict):
        raise LocalFenceUnavailable("maintenance_hold_not_verified")
    ident = hold.get("transaction_id")
    start, expires = hold.get("issued_at"), hold.get("expires_at")
    if (hold.get("active") is not True
            or hold.get("reason") != "root_owned_maintenance_hold"
            or type(ident) is not str or not _TRANSACTION.fullmatch(ident)
            or type(start) is not int or type(expires) is not int
            or start <= 0 or expires <= start or expires - start > 900):
        raise LocalFenceUnavailable("maintenance_hold_not_verified")
    return ident, start, expires


def _release(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        import os
        os.close(fd)


@contextmanager
def local_worker_fence(*, root: Path = Path("/opt/dsm"),
                       lock_dir: Path | None = None) -> Iterator[dict]:
    """Require root-owned hold, hold ALL locks, and reverify process identity.

    The optional lock_dir is for isolated tests only. Installed callers
    always use the fixed /run path. On any busy/missing/unsafe lock or
    identity drift all acquired locks are released and entry is denied.
    """
    transaction = _identity(observe())
    names = tuple(sorted(_KNOWN_WORKERS))
    try:
        folder = _directory(root, create=False, lock_dir=lock_dir)
        with ExitStack() as held:
            # Fixed alphabetical order prevents coordinator deadlocks.
            for name in names:
                fd = _open_lock(folder, name, create=False)
                held.callback(_release, fd)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise LocalFenceUnavailable(
                        "local_worker_cycle_in_flight") from exc

            if _identity(observe()) != transaction:
                raise LocalFenceUnavailable("hold_changed_during_fencing")
            identity = inspect_worker_identity(root=root)
            if (identity.get("status") != "local_identity_verified_only"
                    or identity.get("workers_verified") is not True
                    or identity.get("supervisor_verified") is not True
                    or set(identity.get("workers", {})) != set(names)
                    or identity.get("live_no_drain_authorized") is not False):
                raise LocalFenceUnavailable("local_process_identity_unverified")
            if _identity(observe()) != transaction:
                raise LocalFenceUnavailable("hold_changed_during_observation")
            yield {
                "status": "tracked_local_worker_cycles_fenced",
                "transaction_id": transaction[0],
                "worker_count": len(names),
                "scope": "nine_local_worker_cycles_only",
                "remote_agents_acked": False,
                "external_jobs_acked": False,
                "controller_http_acked": False,
                "live_no_drain_authorized": False,
            }
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, LocalFenceUnavailable):
            raise
        raise LocalFenceUnavailable("local_fence_evidence_unavailable") from exc
