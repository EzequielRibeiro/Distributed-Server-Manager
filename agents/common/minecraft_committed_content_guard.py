"""Fail-closed protection for content sync while Server Pack swap is unarchived.

An outstanding committed/swap journal owns the runtime's managed content.
The materializer must never mutate it via a second content-activation path.
No journal means the normal projection/upgrade path is unchanged.
"""
from __future__ import annotations

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
    if temp.exists() or checkpoint.exists():
        raise MinecraftCommittedContentGuardError("Server Pack archival or journal checkpoint requires recovery before content sync")
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
