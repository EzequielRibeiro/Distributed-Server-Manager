#!/usr/bin/env python3
"""Game-neutral filesystem transaction for shared game-data updates."""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Iterable


def _sibling(target: Path, label: str) -> Path:
    return target.with_name(f".{target.name}.capivara-{label}-{uuid.uuid4().hex}")


def prepare_staging(target: Path) -> Path:
    """Create a private same-filesystem staging tree from the current game data."""
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = _sibling(target, "update-staging")
    if target.exists():
        if not target.is_dir():
            raise ValueError("game-data target must be a directory")
        shutil.copytree(target, staging, symlinks=True)
    else:
        staging.mkdir(mode=0o700)
    return staging


def activate(target: Path, staging: Path) -> Path | None:
    """Atomically switch the staged tree into the canonical target path."""
    target = Path(target).resolve()
    staging = Path(staging).resolve()
    if staging.parent != target.parent or not staging.is_dir():
        raise ValueError("staging must be a sibling directory of target")
    previous = None
    if target.exists():
        previous = _sibling(target, "update-previous")
        os.replace(target, previous)
    try:
        os.replace(staging, target)
    except Exception:
        if previous is not None and previous.exists() and not target.exists():
            os.replace(previous, target)
        raise
    return previous


def rollback(target: Path, previous: Path | None) -> bool:
    """Restore the pre-update tree after a failed post-activation validation."""
    target = Path(target).resolve()
    if previous is None:
        if target.exists():
            shutil.rmtree(target)
        return True
    previous = Path(previous).resolve()
    if not previous.exists():
        return False
    failed = _sibling(target, "update-failed")
    if target.exists():
        os.replace(target, failed)
    try:
        os.replace(previous, target)
    except Exception:
        if failed.exists() and not target.exists():
            os.replace(failed, target)
        raise
    shutil.rmtree(failed, ignore_errors=True)
    return True


def commit(previous: Path | None) -> None:
    if previous is not None:
        shutil.rmtree(previous, ignore_errors=True)


def cleanup_staging(staging: Path | None) -> None:
    if staging is not None:
        shutil.rmtree(staging, ignore_errors=True)


def snapshot_files(paths: Iterable[Path]) -> dict[str, tuple[bool, bytes | None, int | None]]:
    snapshot: dict[str, tuple[bool, bytes | None, int | None]] = {}
    for item in paths:
        path = Path(item)
        try:
            data = path.read_bytes()
            mode = path.stat().st_mode & 0o777
            snapshot[str(path)] = (True, data, mode)
        except FileNotFoundError:
            snapshot[str(path)] = (False, None, None)
    return snapshot


def restore_files(snapshot: dict[str, tuple[bool, bytes | None, int | None]]) -> None:
    """Restore mutable provider metadata such as Steam app manifests."""
    for name, (existed, data, mode) in snapshot.items():
        path = Path(name)
        if not existed:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.capivara-restore-{os.getpid()}")
        temp.write_bytes(data or b"")
        os.chmod(temp, mode or 0o600)
        os.replace(temp, path)


__all__ = ["activate", "cleanup_staging", "commit", "prepare_staging", "restore_files", "rollback", "snapshot_files"]
