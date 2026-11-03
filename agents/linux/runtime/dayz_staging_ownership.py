#!/usr/bin/env python3
"""Opt-in, staging-only DayZ DLC ownership normalizer (issue #977).

NOT wired into update pipelines. An explicit authorization, a transaction staging
name and a privileged caller are required to apply changes. No recursive chown.
All affected inodes are opened with O_NOFOLLOW and validated before modification.
The surrounding game-data transaction remains responsible for atomic activation.
"""
from __future__ import annotations

import os
import re
import stat
from contextlib import ExitStack
from pathlib import Path
from typing import Any

try:
    from .content_discovery_audit import KNOWN_DAYZ_DLC_ROOTS, MAX_ADDON_ENTRIES
except ImportError:
    from content_discovery_audit import KNOWN_DAYZ_DLC_ROOTS, MAX_ADDON_ENTRIES


_STAGE_NAME = re.compile(r"^\.[A-Za-z0-9._-]+\.capivara-update-staging-[a-f0-9]{32}$")
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


class StagingOwnershipError(RuntimeError):
    pass


def _fd(stack: ExitStack, name: str | Path, flags: int, *, parent: int | None = None) -> int:
    args: dict[str, Any] = {} if parent is None else {"dir_fd": parent}
    handle = os.open(name, flags, **args)
    stack.callback(os.close, handle)
    return handle


def _validate(info: os.stat_result, *, directory: bool, device: int) -> None:
    if info.st_dev != device:
        raise StagingOwnershipError("cross_filesystem_entry")
    if directory and not stat.S_ISDIR(info.st_mode):
        raise StagingOwnershipError("not_directory")
    if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise StagingOwnershipError("unsafe_package_inode")


def plan_or_normalize_dayz_staging(
    staging: Path, *, target_uid: int, target_gid: int,
    apply: bool = False, authorized: bool = False,
    transaction_target: Path | None = None,
) -> dict[str, Any]:
    """Review or change known DLC packages only inside an isolated update stage.

    Do not use this as an independent repair tool on production or arbitrary
    directories. Activation, process-stop guarantees and rollback belong to the
    update transaction; this function restores prior ownership on local failure.
    """
    root = Path(staging)
    if not _STAGE_NAME.fullmatch(root.name) or root.is_symlink():
        raise StagingOwnershipError("not_transaction_staging")
    if not isinstance(target_uid, int) or isinstance(target_uid, bool) or target_uid < 0:
        raise StagingOwnershipError("invalid_uid")
    if not isinstance(target_gid, int) or isinstance(target_gid, bool) or target_gid < 0:
        raise StagingOwnershipError("invalid_gid")
    if apply and not authorized:
        raise StagingOwnershipError("explicit_authorization_required")
    if apply and os.geteuid() != 0:
        raise StagingOwnershipError("privileged_agent_required")
    if apply and transaction_target is None:
        raise StagingOwnershipError("transaction_target_required")

    # Keep descriptors open so path swaps after validation cannot redirect
    # fchown onto a different inode. Never follow symlinks in child traversal.
    with ExitStack() as stack:
        root_fd = _fd(stack, root, _FLAGS)
        root_info = os.fstat(root_fd)
        _validate(root_info, directory=True, device=root_info.st_dev)
        if apply:
            # A staging-looking basename alone is not Agent authorization.
            target = Path(transaction_target)
            if (
                not target.is_absolute()
                or target.parent != root.parent
                or not root.name.startswith(
                    f".{target.name}.capivara-update-staging-"
                )
                or target.is_symlink()
            ):
                raise StagingOwnershipError("transaction_target_mismatch")
            target_fd = _fd(stack, target, _FLAGS)
            target_info = os.fstat(target_fd)
            _validate(target_info, directory=True, device=root_info.st_dev)
            if target_info.st_ino == root_info.st_ino:
                raise StagingOwnershipError("staging_aliases_target")
        actions: list[tuple[int, str, int, int]] = []
        # Verify the *names* still point to the same inodes as our open FDs
        # throughout apply; stable FDs alone do not detect Steam replacing a PBO.
        watched: list[tuple[int, str, int]] = []

        def watch(parent_fd: int, name: str, fd: int) -> None:
            watched.append((parent_fd, name, fd))

        def check_watched() -> None:
            for parent_fd, name, fd in watched:
                named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                opened = os.fstat(fd)
                if (named.st_dev, named.st_ino, named.st_mode) != (
                    opened.st_dev, opened.st_ino, opened.st_mode
                ):
                    raise StagingOwnershipError("staged_entry_replaced")

        scanned = []
        for dlc in sorted(KNOWN_DAYZ_DLC_ROOTS):
            if dlc not in os.listdir(root_fd):
                continue
            directory_fd = _fd(stack, dlc, _FLAGS, parent=root_fd)
            _validate(os.fstat(directory_fd), directory=True, device=root_info.st_dev)
            watch(root_fd, dlc, directory_fd)
            addons_fd = _fd(stack, "addons", _FLAGS, parent=directory_fd)
            _validate(os.fstat(addons_fd), directory=True, device=root_info.st_dev)
            watch(directory_fd, "addons", addons_fd)
            names = os.listdir(addons_fd)
            if len(names) > MAX_ADDON_ENTRIES:
                raise StagingOwnershipError("addon_entry_limit")
            package_fds: list[tuple[int, str]] = []
            for name in sorted(names):
                # Reject all symlinks in DLC addons, even those without a PBO
                # suffix; a provider could otherwise trick a later stage.
                entry = os.stat(name, dir_fd=addons_fd, follow_symlinks=False)
                if stat.S_ISLNK(entry.st_mode):
                    raise StagingOwnershipError("symlink_in_addons")
                if name.lower().endswith((".pbo", ".ebo")):
                    file_fd = _fd(stack, name, _FILE_FLAGS, parent=addons_fd)
                    _validate(os.fstat(file_fd), directory=False, device=root_info.st_dev)
                    package_fds.append((file_fd, f"{dlc}/addons/{name}"))
                    watch(addons_fd, name, file_fd)
            if not package_fds:
                raise StagingOwnershipError("known_dlc_without_packages")
            scanned.append({"dlc": dlc, "packages": len(package_fds)})
            for fd, relative in [
                (directory_fd, dlc), (addons_fd, f"{dlc}/addons"), *package_fds,
            ]:
                info = os.fstat(fd)
                if (info.st_uid, info.st_gid) != (target_uid, target_gid):
                    actions.append((fd, relative, info.st_uid, info.st_gid))

        if not apply:
            return {
                "mode": "dry-run", "applied": False, "read_only": True,
                "dlcs": scanned, "candidate_count": len(actions),
                "candidates": [
                    {"path": path, "previous_uid": uid, "previous_gid": gid,
                     "target_uid": target_uid, "target_gid": target_gid}
                    for _, path, uid, gid in actions
                ],
            }

        applied: list[tuple[int, int, int]] = []
        try:
            check_watched()
            for fd, _, old_uid, old_gid in actions:
                check_watched()
                os.fchown(fd, target_uid, target_gid)
                applied.append((fd, old_uid, old_gid))
            check_watched()
        except (OSError, StagingOwnershipError) as exc:
            failed_rollback = []
            for fd, old_uid, old_gid in reversed(applied):
                try:
                    os.fchown(fd, old_uid, old_gid)
                except OSError:
                    failed_rollback.append(fd)
            if failed_rollback:
                raise StagingOwnershipError("normalization_failed_rollback_incomplete") from exc
            raise StagingOwnershipError("normalization_failed_rolled_back") from exc

        return {
            "mode": "apply", "applied": True, "read_only": False,
            "dlcs": scanned, "modified_count": len(applied),
            "transaction_activation_required": True,
        }


__all__ = ["StagingOwnershipError", "plan_or_normalize_dayz_staging"]
