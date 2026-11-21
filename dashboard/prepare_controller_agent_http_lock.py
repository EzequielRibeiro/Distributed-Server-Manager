#!/usr/bin/env python3
"""Root-only one-time provisioning of the stable DSM #928 Controller HTTP lock.

Never overwrite, unlink, chown or truncate an existing witness. This is a
preparatory operator/systemd helper and is NOT automatically invoked by the
updater, Agent or running dashboard. Fail closed on unsafe existing storage.
"""
from __future__ import annotations

import argparse
import grp
import os
from pathlib import Path
import pwd
import stat

from game_uptime_controller_agent_http_flock import (
    LOCK_PATH, ControllerHttpLockUnavailable, _trusted_parents, _open_witness,
)


def provision_controller_agent_http_lock(
    uid: int, gid: int, *, path: Path = LOCK_PATH, parent_uid: int = 0,
) -> Path:
    """Prepare a fixed inode once; fixture path overrides are tests only."""
    path = Path(path)
    if path == LOCK_PATH and os.geteuid() != 0:
        raise ControllerHttpLockUnavailable("root_only_controller_http_provision")
    if not path.is_absolute():
        raise ControllerHttpLockUnavailable("nonabsolute_controller_http_lock")
    if path == LOCK_PATH:
        run = Path("/run")
        info = run.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise ControllerHttpLockUnavailable("untrusted_run")
    # Only create the root-owned container, never alter existing ownership.
    path.parent.mkdir(mode=0o755, exist_ok=True)
    _trusted_parents(path, parent_uid)

    flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    created = False
    try:
        fd = os.open(path, flags, 0o600)
        created = True
    except FileExistsError:
        # Existing inode is NEVER repaired implicitly.
        fd = _open_witness(path, expected_uid=uid, expected_gid=gid,
                           parent_uid=parent_uid)
    try:
        if created:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_size != 0):
                raise ControllerHttpLockUnavailable("invalid_created_witness")
            if (info.st_uid, info.st_gid) != (uid, gid):
                os.fchown(fd, uid, gid)
            os.fchmod(fd, 0o600)
            os.fsync(fd)
    finally:
        os.close(fd)
    folder_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(folder_fd)
    finally:
        os.close(folder_fd)
    # Validate again, using the same exact reader as the HTTP and coordinator.
    fd = _open_witness(path, expected_uid=uid, expected_gid=gid,
                       parent_uid=parent_uid)
    os.close(fd)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--group", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError("root required to provision Controller HTTP lock")
    uid = pwd.getpwnam(args.user).pw_uid
    gid = grp.getgrnam(args.group).gr_gid
    provision_controller_agent_http_lock(uid, gid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
