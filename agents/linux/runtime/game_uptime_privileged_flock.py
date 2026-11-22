#!/usr/bin/env python3
"""DSM #928: opt-in in-flight kernel lock for TWO privileged Linux Agent helpers.

Root-owned, fixed inode outside /opt/capivara-agent. Shared locks witness
only explicitly instrumented processes, not their detached children, other
services, Controller requests or remote Agents. Never emit a positive ACK.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
from typing import Iterator

LOCK_PATH = Path("/run/capivara-dsm/agent-privileged-operations.lock")
ENABLE_ENV = "DSM928_AGENT_PRIVILEGED_FLOCK"


class PrivilegedHelperFenceUnavailable(RuntimeError):
    """Missing/unsafe/busy evidence must not be mistaken for quiescence."""


def _trusted_parent(path: Path, trusted_uid: int) -> None:
    if not path.is_absolute():
        raise PrivilegedHelperFenceUnavailable("lock_path_not_absolute")
    for ancestor in (path.parent.parent, path.parent):
        try:
            info = ancestor.lstat()
        except OSError as exc:
            raise PrivilegedHelperFenceUnavailable("lock_directory_unavailable") from exc
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != trusted_uid
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise PrivilegedHelperFenceUnavailable("unsafe_lock_directory")


def _open_inode(path: Path, trusted_uid: int) -> int:
    """Never create, replace, truncate, or follow a path at runtime."""
    _trusted_parent(path, trusted_uid)
    try:
        before = path.lstat()
        flags = (os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        fd = os.open(path, flags)
    except OSError as exc:
        raise PrivilegedHelperFenceUnavailable("lock_inode_unavailable") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(info.st_mode)
                or (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)
                or info.st_uid != trusted_uid or info.st_gid != os.getegid()
                or info.st_nlink != 1 or info.st_size != 0
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise PrivilegedHelperFenceUnavailable("unsafe_lock_inode")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _acquire(fd: int, mode: int) -> None:
    try:
        fcntl.flock(fd, mode | fcntl.LOCK_NB)
    except OSError as exc:
        raise PrivilegedHelperFenceUnavailable("lock_busy") from exc


@contextmanager
def shared_privileged_helper_lock(*, path: Path = LOCK_PATH,
                                  enabled: bool | None = None,
                                  trusted_uid: int | None = None) -> Iterator[bool]:
    """Retain SH until helper run() exits; without opt-in retain legacy behavior."""
    use = os.environ.get(ENABLE_ENV) == "1" if enabled is None else enabled
    if not use:
        yield False
        return
    path = Path(path)
    uid = os.geteuid() if trusted_uid is None else trusted_uid
    if path == LOCK_PATH and os.geteuid() != 0:
        raise PrivilegedHelperFenceUnavailable("root_required_for_live_lock")
    fd = _open_inode(path, uid)
    try:
        _acquire(fd, fcntl.LOCK_SH)
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def exclusive_privileged_helper_lock(*, path: Path = LOCK_PATH,
                                     trusted_uid: int | None = None
                                     ) -> Iterator[dict[str, object]]:
    """Observe occupied root helpers with EX; not a release/update permit."""
    path = Path(path)
    uid = os.geteuid() if trusted_uid is None else trusted_uid
    if path == LOCK_PATH and os.geteuid() != 0:
        raise PrivilegedHelperFenceUnavailable("root_required_for_live_exclusivity")
    fd = _open_inode(path, uid)
    try:
        _acquire(fd, fcntl.LOCK_EX)
        try:
            yield {
                "status": "two_privileged_helpers_exclusively_locked_only",
                "scope": "two_opted_in_linux_root_helper_runs_on_this_host",
                "privileged_helper_acked": False,
                "external_jobs_acked": False,
                "remote_agents_acked": False,
                "live_no_drain_authorized": False,
            }
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def provision_privileged_helper_lock(*, path: Path = LOCK_PATH,
                                     trusted_uid: int | None = None) -> Path:
    """Root-only for installed path. Create once; never repair existing inode.

    Path override/trusted_uid are intended exclusively for tempfile tests.
    This is not called by Agent, systemd or updater automatically.
    """
    path = Path(path)
    uid = os.geteuid() if trusted_uid is None else trusted_uid
    if not path.is_absolute() or (path == LOCK_PATH and os.geteuid() != 0):
        raise PrivilegedHelperFenceUnavailable("root_only_provision")
    if path == LOCK_PATH:
        run = Path("/run").lstat()
        if (not stat.S_ISDIR(run.st_mode) or run.st_uid != 0
                or run.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise PrivilegedHelperFenceUnavailable("unsafe_run_parent")
    # Never trust a preexisting group/other-writable directory.
    path.parent.mkdir(mode=0o755, exist_ok=True)
    _trusted_parent(path, uid)
    flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path, flags, 0o600)
        created = True
    except FileExistsError:
        fd = _open_inode(path, uid)
        created = False
    try:
        if created:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                    or info.st_nlink != 1 or info.st_size != 0):
                raise PrivilegedHelperFenceUnavailable("bad_created_lock")
            os.fchmod(fd, 0o600)
            os.fsync(fd)
    finally:
        os.close(fd)
    folder_fd = os.open(path.parent, os.O_RDONLY
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(folder_fd)
    finally:
        os.close(folder_fd)
    # Detect a race/replacement rather than silently accepting forged storage.
    fd = _open_inode(path, uid)
    os.close(fd)
    return path
