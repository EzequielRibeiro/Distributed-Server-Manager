#!/usr/bin/env python3
"""Disposable-only crash recovery prototype for staged Minecraft file swaps.

NOT a production executor. Never point it at actual Agent/instance storage.
The caller must create the test marker inside a disposable directory.
No backup, Agent lock, live world integrity, or readiness is provided here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_MARKER = ".capivara-disposable-migration-test"
_ALLOWED_PHASES = {"prepared", "swapping", "swapped", "recovering", "recovered", "committed"}


class CrashRehearsalError(RuntimeError):
    pass


def _sync_dir(directory: Path) -> None:
    fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _root(root: Path) -> Path:
    candidate = Path(root)
    if candidate.is_symlink():
        raise CrashRehearsalError("symlink test root prohibited")
    root = candidate.resolve(strict=True)
    if root == Path("/") or not (root / _MARKER).is_file():
        raise CrashRehearsalError("a marked disposable test root is required")
    # Prevent a copied marker in a real instance runtime from enabling this
    # prototype accidentally: a second explicit process opt-in is required.
    if os.environ.get("CAPIVARA_DISPOSABLE_MIGRATION_REHEARSAL") != "YES":
        raise CrashRehearsalError("disposable test process opt-in is required")
    return root


def _member(root: Path, name: str) -> Path:
    path = root / name
    if path.is_symlink():
        raise CrashRehearsalError("symlink paths are prohibited in the rehearsal")
    return path


def _file_hash(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise CrashRehearsalError("expected regular file is absent")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def _tree_hash(directory: Path) -> str:
    """Merkle-like digest of all test runtime files, not just the loader."""
    if not directory.is_dir() or directory.is_symlink():
        raise CrashRehearsalError("runtime directory missing or symlinked")
    digest = hashlib.sha256()
    files = sorted(directory.rglob("*"))
    for file in files:
        if file.is_symlink() or (not file.is_file() and not file.is_dir()):
            raise CrashRehearsalError("symlinks and special runtime files are prohibited")
        if file.is_dir():
            continue
        relative = file.relative_to(directory).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_file_hash(file)))
    return digest.hexdigest()

def _atomic(root: Path, data: dict) -> None:
    journal = _member(root, "migration-journal.json")
    temp = _member(root, ".migration-journal.tmp")
    with temp.open("x", encoding="utf-8") as out:
        json.dump(data, out, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, journal)
    _sync_dir(root)


def _read(root: Path) -> dict:
    path = _member(root, "migration-journal.json")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CrashRehearsalError("recovery journal is absent or corrupted: manual intervention") from exc
    if not isinstance(result, dict) or result.get("phase") not in _ALLOWED_PHASES:
        raise CrashRehearsalError("recovery journal schema invalid: manual intervention")
    return result


def prepare(root: Path, *, original_hash: str, checkpoint_verified: bool) -> None:
    root = _root(root)
    active = _member(root, "active")
    stage = _member(root, "stage")
    for path in (active, stage):
        if not path.is_dir() or path.is_symlink():
            raise CrashRehearsalError("expected isolated test directories")
    if _member(root, "rollback-runtime").exists() or _member(root, "quarantine-new").exists():
        raise CrashRehearsalError("rollback/quarantine location occupied")
    if _member(root, "migration-journal.json").exists():
        raise CrashRehearsalError("previous journal exists; recover first")
    if checkpoint_verified is not True or _file_hash(active / "neoforge.txt") != original_hash:
        raise CrashRehearsalError("verified checkpoint and expected original file hash required")
    if not (stage / "neoforge.txt").is_file():
        raise CrashRehearsalError("staged test loader is missing")
    _atomic(root, {"schema": 1, "phase": "prepared", "original_hash": original_hash,
                   "original_tree_hash": _tree_hash(active),
                   "staged_tree_hash": _tree_hash(stage)})


def switch(root: Path, *, crash_at: str = "") -> None:
    root = _root(root)
    data = _read(root)
    if data["phase"] != "prepared":
        raise CrashRehearsalError("journal phase does not allow switching")
    active = _member(root, "active")
    stage = _member(root, "stage")
    rollback = _member(root, "rollback-runtime")
    if not active.is_dir() or not stage.is_dir() or rollback.exists():
        raise CrashRehearsalError("test workspace changed since preparation")
    if (_tree_hash(active) != data.get("original_tree_hash") or
            _tree_hash(stage) != data.get("staged_tree_hash")):
        raise CrashRehearsalError("test runtime files changed after checkpoint: revalidate before switch")
    data["phase"] = "swapping"
    _atomic(root, data)
    os.replace(active, rollback)
    _sync_dir(root)
    if crash_at == "after_old_rename":
        os._exit(71)  # intentional subprocess-only fault injection
    os.replace(stage, active)
    _sync_dir(root)
    if crash_at == "after_new_rename":
        os._exit(72)
    data["phase"] = "swapped"
    _atomic(root, data)


def recover(root: Path) -> dict:
    root = _root(root)
    data = _read(root)
    if data["phase"] == "committed":
        raise CrashRehearsalError("committed state cannot be silently rolled back")
    active = _member(root, "active")
    rollback = _member(root, "rollback-runtime")
    quarantine = _member(root, "quarantine-new")
    expected = data.get("original_hash")
    expected_tree = data.get("original_tree_hash")
    if (not isinstance(expected, str) or len(expected) != 64 or
            not isinstance(expected_tree, str) or len(expected_tree) != 64):
        raise CrashRehearsalError("journal has no usable original checksum")
    if data["phase"] == "recovered":
        if _file_hash(active / "neoforge.txt") != expected or _tree_hash(active) != expected_tree:
            raise CrashRehearsalError("recovered files differ from original checksum")
        return {"status": "already_recovered"}
    # A journal can be one step behind fs renames after a process crash.
    # Inspect actual directory state and never discard the rollback copy.
    if rollback.exists():
        if not rollback.is_dir() or _file_hash(rollback / "neoforge.txt") != expected or _tree_hash(rollback) != expected_tree:
            raise CrashRehearsalError("rollback copy missing or incorrect: manual intervention")
        if quarantine.exists() and not (
            data["phase"] == "recovering" and not active.exists() and quarantine.is_dir()
        ):
            raise CrashRehearsalError("quarantine occupied: manual intervention")
        data["phase"] = "recovering"
        _atomic(root, data)
        if active.exists():
            os.replace(active, quarantine)
            _sync_dir(root)
        os.replace(rollback, active)
        _sync_dir(root)
    else:
        # Recovery may have been interrupted AFTER restoring the original.
        if _file_hash(active / "neoforge.txt") != expected or _tree_hash(active) != expected_tree:
            raise CrashRehearsalError("original files unavailable: manual intervention")
    if _file_hash(active / "neoforge.txt") != expected or _tree_hash(active) != expected_tree:
        raise CrashRehearsalError("post-restore hash mismatch")
    data["phase"] = "recovered"
    _atomic(root, data)
    return {"status": "recovered", "quarantine_retained": quarantine.exists()}


def commit(root: Path, *, readiness_passed: bool) -> None:
    root = _root(root)
    data = _read(root)
    if data["phase"] != "swapped" or readiness_passed is not True:
        raise CrashRehearsalError("readiness and completed swap are required")
    if not _member(root, "rollback-runtime").is_dir():
        raise CrashRehearsalError("rollback snapshot missing")
    data["phase"] = "committed"
    _atomic(root, data)
    # Original rollback snapshot is intentionally retained.
