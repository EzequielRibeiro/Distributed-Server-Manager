#!/usr/bin/env python3
"""DSM #928: optional cross-process flock barrier for THREE Agent HTTP routes.

This protects only enroll, heartbeat and uninstall-result dispatchers when
opted in. It is NOT a cross-host fence, a transaction coordinator or a release
gate. An exclusive lock is a local NEGATIVE observation, never permission to
run update.sh --no-drain. Other Controller APIs and background jobs remain
outside this contract.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
from typing import Iterator

LOCK_PATH = Path("/run/capivara-dsm/controller-agent-http.lock")
ENABLE_ENV = "DSM928_CONTROLLER_AGENT_HTTP_FLOCK"


class ControllerHttpLockUnavailable(RuntimeError):
    """Missing/busy/unsafe stable witness: never admit an opted-in mutation."""


def _trusted_parents(path: Path, owner_uid: int) -> None:
    if not path.is_absolute():
        raise ControllerHttpLockUnavailable("nonabsolute_controller_http_lock")
    for candidate in (path.parent.parent, path.parent):
        try:
            info = candidate.lstat()
        except OSError as exc:
            raise ControllerHttpLockUnavailable("controller_http_lock_parent_unavailable") from exc
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise ControllerHttpLockUnavailable("untrusted_controller_http_lock_parent")


def _open_witness(path: Path, *, expected_uid: int, expected_gid: int,
                  parent_uid: int) -> int:
    """Open an existing inode ONLY: no create, truncate, unlink or symlinks."""
    _trusted_parents(path, parent_uid)
    try:
        before = path.lstat()
        flags = (os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        fd = os.open(path, flags)
    except OSError as exc:
        raise ControllerHttpLockUnavailable("controller_http_lock_missing") from exc
    try:
        found = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(found.st_mode)
                or (found.st_dev, found.st_ino) != (before.st_dev, before.st_ino)
                or found.st_uid != expected_uid or found.st_gid != expected_gid
                or found.st_nlink != 1 or found.st_size != 0
                or stat.S_IMODE(found.st_mode) != 0o600):
            raise ControllerHttpLockUnavailable("controller_http_lock_untrusted")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _acquire(fd: int, mode: int) -> None:
    try:
        fcntl.flock(fd, mode | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as exc:
        raise ControllerHttpLockUnavailable("controller_http_lock_busy") from exc


@contextmanager
def shared_controller_agent_http_lock(
    *, lock_path: Path = LOCK_PATH, expected_uid: int | None = None,
    expected_gid: int | None = None, parent_uid: int = 0,
    enabled: bool | None = None,
) -> Iterator[bool]:
    """Hold shared flock for the *whole* request, without waiting.

    When feature is disabled, yields False: compatibility only, NOT fencing.
    When opted in, a missing/busy/unsafe lock fails closed before dispatcher
    mutates anything. Caller must still enforce the existing root-owned hold.
    """
    active = os.environ.get(ENABLE_ENV) == "1" if enabled is None else enabled
    if not active:
        yield False
        return
    path = Path(lock_path)
    uid = os.geteuid() if expected_uid is None else expected_uid
    gid = os.getegid() if expected_gid is None else expected_gid
    fd = _open_witness(path, expected_uid=uid, expected_gid=gid,
                       parent_uid=parent_uid)
    try:
        _acquire(fd, fcntl.LOCK_SH)
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def exclusive_controller_agent_http_lock(
    *, lock_path: Path = LOCK_PATH, expected_uid: int,
    expected_gid: int, parent_uid: int = 0,
) -> Iterator[dict[str, object]]:
    """Acquire the same witness exclusively, fail-fast, no updater hook.

    Fixed production path may be fenced only by root. Fixture paths for
    isolated tests have no privilege override for the real installed path.
    No hold is installed/renewed or removed and no ACK is emitted.
    """
    path = Path(lock_path)
    if path == LOCK_PATH and os.geteuid() != 0:
        raise ControllerHttpLockUnavailable("root_only_controller_http_fence")
    fd = _open_witness(path, expected_uid=expected_uid,
                       expected_gid=expected_gid, parent_uid=parent_uid)
    try:
        _acquire(fd, fcntl.LOCK_EX)
        try:
            yield {
                "status": "three_agent_http_routes_exclusively_locked_only",
                "scope": "opted_in_agent_http_dispatchers_on_this_host_only",
                "controller_http_acked": False,
                "external_jobs_acked": False,
                "remote_agents_acked": False,
                "live_no_drain_authorized": False,
            }
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
