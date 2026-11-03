#!/usr/bin/env python3
"""Per-installation advisory filesystem lock for game-data transactions (#977).

All writers that can replace or mutate the same shared game-data installation
must opt into this lock. Merely holding it does not block external SteamCMD.
The lock lives beside the target because target itself is atomically replaced.
"""
from __future__ import annotations

import errno
import fcntl
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class GameDataUpdateLockError(RuntimeError):
    pass


@contextmanager
def game_data_update_lock(target: Path, *, timeout: float = 3.0) -> Iterator[None]:
    """Hold an exclusive advisory lock keyed by the canonical installation.

    Reject symlinks and non-regular lock files. The lock is intentionally
    not deleted at release: unlinking a flock lock creates split-brain locks.
    """
    target = Path(target)
    if not target.is_absolute() or target.name in ("", ".", "..") or target.is_symlink():
        raise GameDataUpdateLockError("invalid_update_target")
    if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 60:
        raise GameDataUpdateLockError("invalid_lock_timeout")
    try:
        parent = target.parent.resolve(strict=True)
        if not parent.is_dir():
            raise GameDataUpdateLockError("invalid_update_parent")
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise GameDataUpdateLockError("invalid_update_parent") from exc

    lock_fd = None
    try:
        name = f".{target.name}.capivara-game-data-update.lock"
        lock_fd = os.open(
            name,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600, dir_fd=parent_fd,
        )
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise GameDataUpdateLockError("unsafe_update_lock")
        if info.st_dev != os.fstat(parent_fd).st_dev:
            raise GameDataUpdateLockError("cross_filesystem_lock")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise GameDataUpdateLockError("game_data_update_busy") from exc
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise GameDataUpdateLockError("unsafe_update_lock") from exc
        raise
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(parent_fd)


__all__ = ["GameDataUpdateLockError", "game_data_update_lock"]
