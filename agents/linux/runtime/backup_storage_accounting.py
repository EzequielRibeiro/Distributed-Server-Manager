"""Issue #1066: account for existing Agent backup bytes without deleting archives.

Unindexed, invalid and manifest-only TARs consume quota just like restorable
archives. This module never follows symlinks, deletes files, or trusts a DB
row in place of an on-disk file. Failed scans are unknown, never zero.
"""
from __future__ import annotations

import os
import stat
import tarfile
from pathlib import Path
from typing import Any

MANIFEST = ".capivara-backup-manifest.json"
MAX_FILES = 200_000
SMALL_ARCHIVE_PROBE_BYTES = 256 * 1024


def _folder(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise OSError("backup directory unavailable or unsafe")


def _physical_files(root: Path, *, missing_ok: bool = False,
                    allow_shared_hardlinks: bool = False):
    if not root.exists():
        if missing_ok and not root.is_symlink():
            return
        raise OSError("storage directory unavailable")
    _folder(root)
    seen: set[tuple[int, int]] = set()
    count = 0

    def walk(path: Path):
        nonlocal count
        with os.scandir(path) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise OSError("symlink in managed storage tree")
                if stat.S_ISDIR(info.st_mode):
                    yield from walk(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    count += 1
                    if count > MAX_FILES:
                        raise OSError("storage inventory exceeds safe file limit")
                    identity = (info.st_dev, info.st_ino)
                    if info.st_nlink > 1 and not allow_shared_hardlinks:
                        # Backup archives must not be shared with other storage
                        # roots; their ownership and retention remain exclusive.
                        raise OSError("shared hardlinked storage cannot be attributed safely")
                    # Instance-private content may hardlink a shared read-only
                    # Workshop cache. Charge the *full* file size to this
                    # instance, even if the inode is also used elsewhere.
                    # Deduplicate only within the inventory we are walking.
                    if identity not in seen:
                        seen.add(identity)
                        yield Path(entry.path), info
                else:
                    raise OSError("unsupported entry in storage tree")
    yield from walk(root)


def _archive_type(path: Path, size: int) -> str:
    if not path.name.endswith((".tar", ".tar.gz", ".tgz")):
        return "other"
    if size > SMALL_ARCHIVE_PROBE_BYTES:
        return "unverified"
    try:
        with tarfile.open(path, "r:*") as archive:
            members = archive.getmembers()
            if any(m.isfile() and m.name != MANIFEST for m in members):
                return "unverified"
            return "manifest_only"
    except (OSError, ValueError, tarfile.TarError, EOFError):
        return "invalid"


def backup_inventory(backup_root: Path, instance_id: str, *, classify: bool = True) -> dict[str, Any]:
    """Inventory every file under one instance backup directory (incl. history).

    A deleted/missing backup directory is zero, but inaccessible or unsafe
    storage is unknown and must block backup creation.
    """
    root = Path(backup_root)
    if root.is_symlink():
        raise OSError("backup storage root is a symlink")
    if root.exists():
        _folder(root)
    elif not root.parent.is_dir():
        raise OSError("backup storage parent unavailable")
    if (not instance_id or len(instance_id) > 191 or
            any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                for ch in instance_id)):
        raise ValueError("invalid instance ID for backup accounting")
    directory = root / instance_id
    total = files = unverified = invalid = manifest_only = 0
    for path, info in _physical_files(directory, missing_ok=True):
        total += info.st_size
        files += 1
        if classify:
            kind = _archive_type(path, info.st_size)
            if kind == "manifest_only":
                manifest_only += 1
            elif kind == "invalid":
                invalid += 1
            elif kind == "unverified":
                unverified += 1
    return {
        "status": "ok", "bytes": total, "file_count": files,
        "manifest_only_count": manifest_only,
        "invalid_count": invalid,
        "unverified_archive_count": unverified,
        "restorability_confirmed": False,  # inventory alone cannot prove restore
    }



def physical_backup_catalog(backup_root: Path, instance_id: str,
                            *, limit: int = 1024) -> dict[str, Any]:
    """Read-only, bounded, *unverified* archive listing for customer inventory.

    The client sees only names and sizes, never host paths. A file being
    present does not prove it is a valid or restorable backup. Enumeration
    rejects unsafe paths; deletion is a separate authorized operation.
    """
    from datetime import datetime, timezone

    if not instance_id or len(instance_id) > 191 or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for ch in instance_id
    ) or instance_id in {".", ".."}:
        raise ValueError("invalid instance ID for physical backup catalog")
    if not 1 <= limit <= 2048:
        raise ValueError("physical backup catalog limit out of range")
    base = Path(backup_root)
    if base.is_symlink() or not base.is_dir():
        raise OSError("backup storage root unavailable or unsafe")
    directory = base / instance_id
    if directory.is_symlink():
        raise OSError("backup instance directory is a symlink")
    if not directory.exists():
        return {
            "status": "ok", "instance_id": instance_id, "files": [],
            "total_files": 0, "total_bytes": 0, "truncated": False,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    _folder(directory)
    items = []
    total = 0
    count = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError("unsafe physical backup inventory entry")
            count += 1
            if count > MAX_FILES:
                raise OSError("physical backup inventory exceeds safe limit")
            total += info.st_size
            # .tar, .tgz, and .tar.gz are supported by _artifact() and delete.
            filename = entry.name
            suffix = next((ext for ext in (".tar.gz", ".tgz", ".tar")
                           if filename.endswith(ext)), "")
            backup_id = filename[:-len(suffix)] if suffix else None
            if not backup_id or any(
                ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                for ch in backup_id
            ) or len(backup_id) > 191 or backup_id in {".", ".."}:
                backup_id = None
            items.append({
                "filename": filename,
                "backup_id": backup_id,
                "size_bytes": info.st_size,
                "modified_at": datetime.fromtimestamp(
                    info.st_mtime, timezone.utc
                ).isoformat(),
                "kind": "archive_unverified" if backup_id else "other_file",
                "physical_verification": "not_checked",
            })
    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return {
        "status": "ok",
        "instance_id": instance_id,
        "files": items[:limit],
        "total_files": count,
        "total_bytes": total,
        "truncated": count > limit,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def quota_snapshot(record: dict[str, Any], backup_root: Path, *,
                   classify: bool = False) -> dict[str, Any]:
    """Snapshot private instance bytes + physical archives with overlap handled."""
    iid = str(record.get("instance_id") or "")
    archives = backup_inventory(backup_root, iid, classify=classify)
    instance_raw = (record.get("instance_state_root") or record.get("files_root")
                    or record.get("configuration_root"))
    if not isinstance(instance_raw, str) or not instance_raw.startswith("/"):
        raise OSError("instance private state root unavailable")
    state_root = Path(instance_raw)
    instance_used = sum(info.st_size for _, info in _physical_files(
        state_root, allow_shared_hardlinks=True))
    # If the backup directory is already part of the counted instance tree,
    # avoid adding the same bytes twice.
    backup_path = Path(backup_root) / iid
    try:
        nested = backup_path.resolve().is_relative_to(state_root.resolve())
    except (OSError, RuntimeError):
        raise OSError("cannot establish backup path containment") from None
    backup_bytes = int(archives["bytes"])
    private_bytes = max(0, instance_used - backup_bytes) if nested else instance_used
    return {
        **archives,
        "instance_used_bytes": private_bytes,
        "backup_used_bytes": backup_bytes,
        "total_used_bytes": instance_used if nested else instance_used + backup_bytes,
        "backup_nested_in_instance": nested,
    }


def source_size(paths: list[Path], source_root: Path) -> int:
    """Conservative bound for creating a new TAR (no double counting)."""
    root = Path(source_root).resolve()
    seen: set[tuple[int, int]] = set()
    total = 0
    for candidate in paths:
        item = Path(candidate)
        if not item.resolve().is_relative_to(root):
            raise ValueError("backup source escaped instance root")
        if item.is_file():
            files = [(item, item.stat())]
        else:
            files = _physical_files(item, allow_shared_hardlinks=True)
        for _, info in files:
            identity = (info.st_dev, info.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            total += info.st_size
    return total
