"""Fail-closed protection for content sync while Server Pack swap is unarchived.

An outstanding committed/swap journal owns the runtime's managed content.
The materializer must never mutate it via a second content-activation path.
No journal means the normal projection/upgrade path is unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class MinecraftCommittedContentGuardError(RuntimeError):
    pass


def refuse_content_sync_during_serverpack_transaction(instance_root: Path) -> None:
    """Check only transaction metadata; does not open or mutate runtime files."""
    root = Path(instance_root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise MinecraftCommittedContentGuardError("unsafe Minecraft instance root for content sync")
    control = root / ".dsm"
    if control.is_symlink() or (control.exists() and not control.is_dir()):
        raise MinecraftCommittedContentGuardError("unsafe Minecraft migration control directory")
    if not control.exists():
        return
    journal = control / "minecraft-serverpack-migration.json"
    temp = control / ".minecraft-serverpack-migration.json.tmp"
    checkpoint = control / "minecraft-serverpack-archive-checkpoint.json"
    for entry in (journal, temp, checkpoint):
        if entry.is_symlink():
            raise MinecraftCommittedContentGuardError("unsafe Server Pack transaction evidence")
    archive_temp = control / ".minecraft-serverpack-archive-checkpoint.tmp"
    if archive_temp.is_symlink() or archive_temp.exists() or temp.exists():
        raise MinecraftCommittedContentGuardError("unfinished Server Pack journal or archive checkpoint")
    if checkpoint.exists():
        if not checkpoint.is_file():
            raise MinecraftCommittedContentGuardError("unsafe archival checkpoint")
        try:
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            sha = saved["sha256"]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise MinecraftCommittedContentGuardError("unreadable archival checkpoint") from exc
        if (not isinstance(saved, dict) or saved.get("schema_version") != 1
                or not isinstance(sha, str) or len(sha) != 64
                or any(char not in "0123456789abcdef" for char in sha)):
            raise MinecraftCommittedContentGuardError("invalid archival checkpoint")
        # The checkpoint intentionally survives a successful archive. Only the
        # fully moved historical journal and rollback prove finalization.
        history = control / "migration-history"
        archived = history / sha[:24]
        historical_journal = archived / "minecraft-serverpack-migration.json"
        retained = archived / "runtime.migration-rollback"
        old_rollback = root / "runtime.migration-rollback"
        if (history.is_symlink() or archived.is_symlink()
                or historical_journal.is_symlink() or retained.is_symlink()
                or old_rollback.is_symlink()):
            raise MinecraftCommittedContentGuardError("unsafe archival evidence")
        if journal.exists() or journal.is_symlink():
            raise MinecraftCommittedContentGuardError("Server Pack archival is still pending")
        if (not historical_journal.is_file() or not retained.is_dir()
                or old_rollback.exists()
                or hashlib.sha256(historical_journal.read_bytes()).hexdigest() != sha):
            raise MinecraftCommittedContentGuardError("Server Pack archival is incomplete")
        return
    if not journal.exists():
        return
    if not journal.is_file():
        raise MinecraftCommittedContentGuardError("Server Pack transaction journal is not a regular file")
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MinecraftCommittedContentGuardError("unreadable Server Pack transaction journal") from exc
    if (not isinstance(data, dict) or data.get("kind") != "CapivaraMinecraftServerPackMigrationSwap"
            or data.get("phase") not in {"prepared", "swapping", "swapped", "recovering", "recovered", "committed"}):
        raise MinecraftCommittedContentGuardError("invalid Server Pack transaction journal")
    # Until a committed swap has been safely archived, content activation must
    # not add/remove/overwrite any managed mod or override file.
    raise MinecraftCommittedContentGuardError(
        "Server Pack transaction must be explicitly finalized or recovered before content sync"
    )
