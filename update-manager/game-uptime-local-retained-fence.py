#!/usr/bin/env python3
"""#928 local retained-fence primitive; not an update authorization.

A privileged coordinator may hold preprovisioned kernel locks throughout a
transaction. No lock files are created, replaced, or removed. This primitive
does not fence remote Agents, external jobs, or uninstrumented mutators.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
from typing import Iterator

from importlib.machinery import SourceFileLoader
import importlib.util

HERE = Path(__file__).resolve().parent
_loader = SourceFileLoader("dsm928_fence_inventory", str(HERE / "game-uptime-local-fence-diagnostics.py"))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
_inventory = importlib.util.module_from_spec(_spec)
_loader.exec_module(_inventory)


class RetainedFenceBlocked(RuntimeError):
    pass


def _open_existing(path: Path) -> int:
    if not path.is_absolute() or path.is_symlink():
        raise RetainedFenceBlocked("untrusted_lock_path")
    for parent in (path.parent.parent, path.parent):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise RetainedFenceBlocked("untrusted_lock_directory")
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid not in (0, os.geteuid())):
        raise RetainedFenceBlocked("untrusted_lock_file")
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK
                 | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_CLOEXEC", 0))
    after = os.fstat(fd)
    if ((before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or not stat.S_ISREG(after.st_mode)):
        os.close(fd)
        raise RetainedFenceBlocked("lock_inode_changed")
    return fd


@contextmanager
def retain_local_fences() -> Iterator[dict[str, object]]:
    """Nonblocking, all-or-nothing acquisition of installed local locks.

    The caller MUST retain the context for the full transaction and independently
    establish authenticated remote ACKs and durable crash recovery. Exit releases
    every lock; it never clears a persistent maintenance hold or pending journal.
    """
    paths = [_inventory.CONTROLLER_LOCK] + [
        _inventory.WORKER_LOCK_DIR / (name + ".lock")
        for name in _inventory.WORKERS
    ]
    acquired: list[int] = []
    try:
        for path in paths:
            try:
                fd = _open_existing(path)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (OSError, BlockingIOError) as exc:
                    os.close(fd)
                    raise RetainedFenceBlocked("lock_busy_or_unavailable") from exc
            except (OSError, ValueError) as exc:
                raise RetainedFenceBlocked("lock_missing_or_untrusted") from exc
            acquired.append(fd)
        yield {
            "status": "local_kernel_locks_retained_only",
            "lock_count": len(acquired),
            "controller_worker_lock_coverage_only": True,
            "remote_agents_acked": False,
            "external_jobs_acked": False,
            "crash_recovery_verified": False,
            "live_no_drain_authorized": False,
        }
    finally:
        for fd in reversed(acquired):
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
