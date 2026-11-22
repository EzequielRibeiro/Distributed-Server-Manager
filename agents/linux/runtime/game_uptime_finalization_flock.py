#!/usr/bin/env python3
"""#928: opt-in kernel in-flight witness for a detached, unprivileged Agent child.

The installed inode is root-owned, group-accessible to capivara-agent, and
lives outside the replaceable Agent tree. A free EX proves ONLY the absence
of cooperating finalization workers on ONE host at that instant. It is not
a distributed ACK or permission for update.sh --no-drain.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import grp
import os
from pathlib import Path
import stat
from typing import Iterator

LOCK_PATH = Path("/run/capivara-dsm/agent-finalization-operations.lock")
ENABLE_ENV = "DSM928_AGENT_FINALIZATION_FLOCK"
AGENT_GROUP = "capivara-agent"


class FinalizationFenceUnavailable(RuntimeError):
    """An absent, unsafe or occupied inode cannot prove local quiescence."""


def _identities(path: Path, trusted_uid: int | None,
                group_gid: int | None) -> tuple[int, int]:
    if path == LOCK_PATH:
        if trusted_uid is not None or group_gid is not None:
            raise FinalizationFenceUnavailable("installed_identity_is_fixed")
        try:
            return 0, grp.getgrnam(AGENT_GROUP).gr_gid
        except KeyError as exc:
            raise FinalizationFenceUnavailable("agent_group_unavailable") from exc
    if trusted_uid is None or group_gid is None:
        raise FinalizationFenceUnavailable("fixture_identity_required")
    return trusted_uid, group_gid


def _check_parents(path: Path, owner_uid: int) -> None:
    if not path.is_absolute():
        raise FinalizationFenceUnavailable("lock_path_not_absolute")
    for parent in (path.parent.parent, path.parent):
        try:
            info = parent.lstat()
        except OSError as exc:
            raise FinalizationFenceUnavailable("lock_parent_unavailable") from exc
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise FinalizationFenceUnavailable("unsafe_lock_parent")


def _open_inode(path: Path, owner_uid: int, agent_gid: int) -> int:
    _check_parents(path, owner_uid)
    flags = (os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    try:
        before = path.lstat()
        fd = os.open(path, flags)
    except OSError as exc:
        raise FinalizationFenceUnavailable("lock_inode_unavailable") from exc
    try:
        current = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or (before.st_dev, before.st_ino)
                    != (current.st_dev, current.st_ino)
                or current.st_uid != owner_uid or current.st_gid != agent_gid
                or stat.S_IMODE(current.st_mode) != 0o660
                or current.st_nlink != 1 or current.st_size != 0):
            raise FinalizationFenceUnavailable("unsafe_lock_inode")
        if (path == LOCK_PATH and os.geteuid() != 0
                and agent_gid not in (os.getegid(), *os.getgroups())):
            raise FinalizationFenceUnavailable("agent_group_membership_missing")
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def shared_finalization_lock(*, path: Path = LOCK_PATH,
                             enabled: bool | None = None,
                             trusted_uid: int | None = None,
                             group_gid: int | None = None) -> Iterator[bool]:
    """Hold SH throughout the detached child operation when explicitly opted in."""
    if enabled is None:
        enabled = os.environ.get(ENABLE_ENV) == "1"
    if not enabled:
        yield False
        return
    path = Path(path)
    owner_uid, agent_gid = _identities(path, trusted_uid, group_gid)
    fd = _open_inode(path, owner_uid, agent_gid)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            raise FinalizationFenceUnavailable("finalization_lock_busy") from exc
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def exclusive_finalization_lock(*, path: Path = LOCK_PATH,
                                trusted_uid: int | None = None,
                                group_gid: int | None = None
                                ) -> Iterator[dict[str, object]]:
    """Root coordinator's local EX witness; never a release authorization."""
    path = Path(path)
    if path == LOCK_PATH and os.geteuid() != 0:
        raise FinalizationFenceUnavailable("root_required_for_exclusive")
    owner_uid, agent_gid = _identities(path, trusted_uid, group_gid)
    fd = _open_inode(path, owner_uid, agent_gid)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise FinalizationFenceUnavailable("finalization_lock_busy") from exc
        try:
            yield {
                "status": "one_host_finalization_child_lock_exclusive",
                "scope": "opted_in_detached_finalization_children_only",
                "all_jobs_opted_in_verified": False,
                "external_jobs_acked": False,
                "remote_agents_acked": False,
                "live_no_drain_authorized": False,
            }
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def provision_finalization_lock(*, path: Path = LOCK_PATH,
                               trusted_uid: int | None = None,
                               group_gid: int | None = None) -> Path:
    """Explicit root-only initial provisioning. Never repair an existing inode.

    Custom identities/paths exist ONLY for disposable test fixtures. Neither
    the Agent nor the updater invokes this automatically.
    """
    path = Path(path)
    if path == LOCK_PATH and os.geteuid() != 0:
        raise FinalizationFenceUnavailable("root_required_for_provisioning")
    owner_uid, agent_gid = _identities(path, trusted_uid, group_gid)
    if path == LOCK_PATH:
        run = Path("/run").lstat()
        if (not stat.S_ISDIR(run.st_mode) or run.st_uid != 0
                or run.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise FinalizationFenceUnavailable("unsafe_run_parent")
    if not path.is_absolute():
        raise FinalizationFenceUnavailable("lock_path_not_absolute")
    path.parent.mkdir(mode=0o755, exist_ok=True)
    _check_parents(path, owner_uid)
    flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path, flags, 0o600)
        created = True
    except FileExistsError:
        fd = _open_inode(path, owner_uid, agent_gid)
        created = False
    try:
        if created:
            if os.geteuid() != owner_uid:
                raise FinalizationFenceUnavailable("untrusted_creator")
            os.fchown(fd, owner_uid, agent_gid)
            os.fchmod(fd, 0o660)
            os.fsync(fd)
    finally:
        os.close(fd)
    fd = _open_inode(path, owner_uid, agent_gid)
    os.close(fd)
    return path
