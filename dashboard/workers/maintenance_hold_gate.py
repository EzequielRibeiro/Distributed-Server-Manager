#!/usr/bin/env python3
"""Local #928 maintenance hold and in-flight Worker operation evidence.

The root-owned hold remains read-only. This module records *one* Worker
operation with a kernel flock while it runs. A free lock is NOT an authorized
no-drain ACK: the caller must still prove that the expected process exists,
that all mutators are covered, and that remote Agents are quiescent.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
import subprocess
from pathlib import Path
import stat
import sys
from typing import Iterator

_RUNTIME = Path(__file__).resolve().parents[2] / "agents" / "linux" / "runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.append(str(_RUNTIME))

from game_uptime_maintenance_hold import observe

# Deliberately enumerate known Worker identities rather than trusting a
# caller-controlled path. More Worker entrypoints can join this contract.
_KNOWN_WORKERS = frozenset({
    "scheduler_worker",
    "automation_worker",
    "content_update_worker",
    "maintenance_worker",
    "observability_retention_worker",
    "content_upload_retention_worker",
    "database_intelligence_worker",
    "hybrid_agent_worker",
    "hybrid_customer_workspace_worker",
})
# Root-owned parent and root-owned directory are outside /opt/dsm and
# survive replacement of the application tree. Lock files are pre-provisioned
# by a privileged systemd ExecStartPre; workers never create or unlink them.
LOCK_DIRECTORY = Path("/run/capivara-dsm/worker-operations")


def maintenance_paused() -> bool:
    """Skip the next mutating cycle while local root-owned hold is present."""
    return observe()["active"]


def _directory(root: Path, *, create: bool,
               lock_dir: Path | None = None) -> Path:
    """Validate fixed, installer-provisioned lock storage without creating it.

    `root` and `create` are retained for existing callers only. The lock
    directory must NOT follow the DSM install root; a custom lock_dir is
    reserved for isolated tests and never supplied by runtime entrypoints.
    """
    del root, create
    folder = LOCK_DIRECTORY if lock_dir is None else Path(lock_dir)
    trusted_uid = 0 if lock_dir is None else os.geteuid()
    if lock_dir is None:
        run = Path("/run").lstat()
        if (not stat.S_ISDIR(run.st_mode) or run.st_uid != 0
                or run.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise RuntimeError("untrusted /run parent")
    parent = folder.parent.lstat()
    info = folder.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != trusted_uid
            or parent.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not stat.S_ISDIR(info.st_mode) or info.st_uid != trusted_uid
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        raise RuntimeError("untrusted persistent Worker lock directory")
    return folder


def _open_lock(folder: Path, worker: str, *, create: bool) -> int:
    if worker not in _KNOWN_WORKERS:
        raise ValueError("unrecognized worker identity")
    # Existing root-provisioned inode ONLY; never O_CREAT/O_TRUNC/O_EXCL.
    # Root-owned parent blocks Worker users from unlinking/replacing it.
    del create
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(folder / (worker + ".lock"), flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise RuntimeError("untrusted Worker lock inode")
    except BaseException:
        os.close(fd)
        raise
    return fd

@contextmanager
def tracked_operation(worker: str, *, root: Path) -> Iterator[bool]:
    """Hold an exclusive kernel lock during an entire mutating Worker cycle.

    The hold is checked AFTER taking the lock, so a future coordinator can
    acquire and retain this same lock across the marker creation/transaction
    boundary. No operations run if the evidence file cannot be established.
    """
    folder = _directory(root, create=True)
    fd = _open_lock(folder, worker, create=True)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield not maintenance_paused()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def inspect_operation(worker: str, *, root: Path) -> dict[str, object]:
    """Read-only busy/unknown/lock-free evidence, NEVER an update approval."""
    result: dict[str, object] = {
        "worker": worker,
        "status": "unverified",
        "live_no_drain_authorized": False,
    }
    try:
        folder = _directory(root, create=False)
        fd = _open_lock(folder, worker, create=False)
    except (OSError, ValueError, RuntimeError):
        result["reason"] = "missing_or_untrusted_worker_evidence"
        return result
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result["status"] = "operation_in_flight"
        else:
            result["status"] = "lock_free_process_identity_unverified"
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
    return result


def scheduler_tick() -> int:
    """Run one scheduler update while holding its kernel in-flight witness.

    The standalone --once mode in scheduler_worker.sh is an internal operation
    and does not confer transactional quiescence: the coordinator must still
    fence all processes and verify their identities before any live update.
    """
    root = Path(os.environ.get("DSM_ROOT", "/opt/dsm")).resolve()
    worker = root / "dashboard" / "workers" / "scheduler_worker.sh"
    if worker.is_symlink() or not worker.is_file():
        return 2
    with tracked_operation("scheduler_worker", root=root) as admitted:
        if not admitted:
            return 2
        try:
            return subprocess.run(
                ("/bin/bash", str(worker), "--once"),
                timeout=45, check=False,
            ).returncode
        except (OSError, subprocess.SubprocessError):
            return 1


if __name__ == "__main__":
    # The only CLI operation is the local scheduler tick. No write/clear
    # access to the root-owned maintenance marker is exposed.
    raise SystemExit(scheduler_tick() if sys.argv[1:] == ["--scheduler-tick"] else 2)
