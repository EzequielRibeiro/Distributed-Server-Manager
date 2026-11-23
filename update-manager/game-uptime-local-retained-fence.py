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
    # Worker lock files can be owned by their dedicated service UID. The
    # trusted root-owned directories, 0600 mode, and retained inode identity
    # are the trust boundary; requiring root ownership rejects valid locks.
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600):
        raise RetainedFenceBlocked("untrusted_lock_file")
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK
                 | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_CLOEXEC", 0))
    try:
        after = os.fstat(fd)
        if ((before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                or not stat.S_ISREG(after.st_mode)
                or after.st_nlink != 1
                or after.st_uid != before.st_uid
                or stat.S_IMODE(after.st_mode) != 0o600):
            raise RetainedFenceBlocked("lock_inode_changed")
        return fd
    except BaseException:
        os.close(fd)
        raise


def verify_retained_fences(paths: list[Path], fds: list[int]) -> None:
    """Revalidate all held lock identities at transaction checkpoints.

    This is a local-only assertion, not proof of remote quiescence.
    """
    if len(paths) != len(fds) or not paths:
        raise RetainedFenceBlocked("retained_lock_inventory_mismatch")
    for path, fd in zip(paths, fds):
        try:
            named = path.lstat()
            locked = os.fstat(fd)
            if (not stat.S_ISREG(named.st_mode)
                    or (named.st_dev, named.st_ino) !=
                    (locked.st_dev, locked.st_ino)
                    or named.st_nlink != 1
                    or named.st_uid != locked.st_uid
                    or stat.S_IMODE(named.st_mode) != 0o600):
                raise RetainedFenceBlocked("retained_lock_identity_changed")
        except OSError as exc:
            raise RetainedFenceBlocked("retained_lock_unavailable") from exc


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
    # A caller must be privileged to hold the preprovisioned controller
    # and worker lock inodes. No unprivileged code may impersonate the
    # transaction coordinator or obtain an apparent local fence.
    if os.geteuid() != 0:
        raise RetainedFenceBlocked("root_coordinator_required")
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
            # Check the pathname still names the locked inode. A replaced
            # lock file would otherwise leave an apparently retained fence
            # that no Worker or Controller actually observes.
            try:
                named = path.lstat()
                locked = os.fstat(fd)
                if ((named.st_dev, named.st_ino) !=
                        (locked.st_dev, locked.st_ino)
                        or named.st_nlink != 1
                        or named.st_uid != locked.st_uid
                        or stat.S_IMODE(named.st_mode) != 0o600):
                    raise RetainedFenceBlocked("locked_path_replaced")
            except OSError as exc:
                raise RetainedFenceBlocked("locked_path_unavailable") from exc
        verify_retained_fences(paths, acquired)
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
