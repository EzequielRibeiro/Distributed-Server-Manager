"""Read-only verification of a committed Server Pack migration across a crash.

The outer scheduler must hold runtime_lock.instance_lock. Never guess a
history directory by probing multiple migrations: use the durable archive
checkpoint which was fsynced before the first filesystem rename.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class CheckpointVerificationError(RuntimeError):
    pass


def _json_file(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise CheckpointVerificationError("journal missing or unsafe")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise CheckpointVerificationError("journal unreadable") from exc
    if not isinstance(value, dict):
        raise CheckpointVerificationError("journal is not a mapping")
    return value, raw


def discover_committed_checkpoint(
    root: Path, *, plan_sha256: str, loader_version: str,
) -> dict[str, Any]:
    """Identify active or archived committed journal, without modifying files.

    An archived journal must match the durable checkpoint digest and live
    rollback directory must not be present. This is NOT proof of a successful
    service restart; the Agent must check that separately.
    """
    root = Path(root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise CheckpointVerificationError("invalid instance root")
    control = root / ".dsm"
    if control.is_symlink() or not control.is_dir():
        raise CheckpointVerificationError("invalid control directory")
    active = control / "minecraft-serverpack-migration.json"
    checkpoint = control / "minecraft-serverpack-archive-checkpoint.json"
    history = control / "migration-history"
    if active.is_symlink() or checkpoint.is_symlink() or history.is_symlink():
        raise CheckpointVerificationError("unsafe migration path")
    if not loader_version or not isinstance(plan_sha256, str) or len(plan_sha256) != 64 or any(
        x not in "0123456789abcdef" for x in plan_sha256
    ):
        raise CheckpointVerificationError("invalid migration identity")
    saved = None
    if checkpoint.exists():
        saved, _ = _json_file(checkpoint)
        digest = saved.get("sha256")
        if (saved.get("schema_version") != 1 or not isinstance(digest, str)
                or len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest)):
            raise CheckpointVerificationError("invalid archive checkpoint")
    if active.exists():
        journal, raw = _json_file(active)
        digest = hashlib.sha256(raw).hexdigest()
        if saved and digest != saved["sha256"]:
            raise CheckpointVerificationError("active journal disagrees with archived checkpoint")
        location = "active"
    else:
        if not saved or not history.is_dir():
            raise CheckpointVerificationError("committed journal not found")
        digest = saved["sha256"]
        archive = history / digest[:24]
        if archive.is_symlink() or not archive.is_dir():
            raise CheckpointVerificationError("unsafe archive directory")
        journal, raw = _json_file(archive / "minecraft-serverpack-migration.json")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise CheckpointVerificationError("archived journal SHA mismatch")
        if (root / "runtime.migration-rollback").exists():
            raise CheckpointVerificationError("rollback remains outside archive")
        rollback = archive / "runtime.migration-rollback"
        if rollback.is_symlink() or not rollback.is_dir():
            raise CheckpointVerificationError("archived rollback missing")
        location = "archived"
    if (journal.get("phase") != "committed"
            or journal.get("migration_plan_sha256") != plan_sha256
            or journal.get("target_loader_version") != loader_version):
        raise CheckpointVerificationError("committed journal identity mismatch")
    return {"status": location, "sha256": digest, "journal": journal}
