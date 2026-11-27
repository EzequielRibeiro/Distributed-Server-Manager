#!/usr/bin/env python3
"""Root-only, idempotent provisioning of stable #928 Worker flock inodes.

No updater or process receives a no-drain authorization from this script.
Workers can read/write their own lock files but cannot unlink them because
the directory and its parent are root-owned and not group/other writable.
Never remove, truncate, chown or replace an existing lock inode.
"""
from __future__ import annotations

import argparse
import grp
import os
from pathlib import Path
import pwd
import stat

from maintenance_hold_gate import LOCK_DIRECTORY, _KNOWN_WORKERS

CONTROLLER_RUNTIME = Path("/run/capivara-dsm")
PERSISTENT_STATE = Path("/var/lib/capivara-dsm-928")


def _root_directory(path: Path, owner: int) -> None:
    item = path.lstat()  # follows no symlinks
    if (not stat.S_ISDIR(item.st_mode) or item.st_uid != owner
            or item.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        raise RuntimeError(f"unsafe Worker lock parent: {path}")


def _prepare_inode(path: Path, uid: int, gid: int) -> None:
    baseflags = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    baseflags |= getattr(os, "O_NONBLOCK", 0)
    created = False
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | baseflags, 0o600)
        created = True
    except FileExistsError:
        fd = os.open(path, os.O_RDONLY | baseflags)
    try:
        if created:
            fresh = os.fstat(fd)
            if (fresh.st_uid, fresh.st_gid) != (uid, gid):
                os.fchown(fd, uid, gid)
            os.fchmod(fd, 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                or info.st_gid != gid or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 0):
            raise RuntimeError(f"unsafe existing operation lock: {path.name}")
    finally:
        os.close(fd)

def _prepare_directory(path: Path, owner: int, *, mode: int) -> None:
    """Create only missing directories; never repair pre-existing evidence."""
    _root_directory(path.parent, owner)
    created = False
    try:
        path.mkdir(mode=mode)
        created = True
    except FileExistsError:
        pass
    _root_directory(path, owner)
    if created:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if info.st_uid != owner:
                raise RuntimeError(f"unexpected directory owner: {path}")
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
    if stat.S_IMODE(path.lstat().st_mode) != mode:
        raise RuntimeError(f"unexpected maintenance directory mode: {path}")


def prepare_controller(uid: int, gid: int, *,
                       runtime: Path = CONTROLLER_RUNTIME,
                       state: Path = PERSISTENT_STATE,
                       parent_owner: int = 0) -> Path:
    """Provision empty stable infrastructure, not a maintenance hold or ACK."""
    runtime, state = Path(runtime), Path(state)
    if runtime == CONTROLLER_RUNTIME or state == PERSISTENT_STATE:
        if (runtime != CONTROLLER_RUNTIME or state != PERSISTENT_STATE
                or os.geteuid() != 0 or parent_owner != 0):
            raise PermissionError("installed Controller paths require root")
        _root_directory(Path("/var"), 0)
    else:
        import tempfile
        tmp = Path(tempfile.gettempdir()).resolve()
        if (not runtime.is_absolute() or not state.is_absolute()
                or tmp not in runtime.parents or tmp not in state.parents
                or runtime == state or parent_owner != os.geteuid()):
            raise PermissionError("disposable provisioning paths required")
    # The unprivileged hold reader must be able to traverse both roots.
    _prepare_directory(runtime, parent_owner, mode=0o755)
    _prepare_directory(state, parent_owner, mode=0o755)
    _prepare_directory(state / "no-drain-wire-receipts", parent_owner,
                       mode=0o700)
    lock = runtime / "controller-agent-http.lock"
    _prepare_inode(lock, uid, gid)
    _prepare_inode(runtime / "controller-agent-http-admission.lock", uid, gid)
    return lock


def prepare(uid: int, gid: int, *, directory: Path = LOCK_DIRECTORY,
            parent_owner: int = 0) -> list[Path]:
    """Provision only missing inodes. Refuse inconsistent existing evidence.

    The directory/parent overrides exist only for tempfile tests; systemd
    invokes main() with the hardcoded /run location and real uid/gid.
    """
    folder = Path(directory)
    if folder == LOCK_DIRECTORY:
        _root_directory(Path("/run"), 0)
    parent = folder.parent
    parent.mkdir(mode=0o755, exist_ok=True)
    _root_directory(parent, parent_owner)
    folder.mkdir(mode=0o755, exist_ok=True)
    _root_directory(folder, parent_owner)
    files = []
    for worker in sorted(_KNOWN_WORKERS):
        path = folder / (worker + ".lock")
        _prepare_inode(path, uid, gid)
        files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--controller-only", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError("Worker lock provisioning requires root")
    uid = pwd.getpwnam(args.user).pw_uid
    gid = grp.getgrnam(args.group).gr_gid
    if args.controller_only:
        prepare_controller(uid, gid)
    else:
        prepare(uid, gid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
