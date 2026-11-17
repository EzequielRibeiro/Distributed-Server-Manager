"""Fail-closed, read-only preflight for a new Minecraft Server Pack transaction.

This is an early UX/safety guard, not a replacement for the materializer's
exclusive-lock and filesystem checks. A previous committed journal must be
explicitly finalized/archived before a new migration may begin.
"""
from __future__ import annotations

from pathlib import Path


class MinecraftServerPackPreflightError(RuntimeError):
    pass


def require_empty_serverpack_slot(instance_root: Path) -> None:
    """Reject old transaction evidence before stopping or backing up the game.

    Never remove or automatically archive anything. This check is intentionally
    conservative and must also be repeated under the privileged instance lock.
    """
    root = Path(instance_root)
    if not root.is_dir() or root.is_symlink():
        raise MinecraftServerPackPreflightError("unsafe instance state directory")
    control = root / ".dsm"
    if control.is_symlink() or not control.is_dir():
        raise MinecraftServerPackPreflightError("instance migration control directory is unavailable or unsafe")
    entries = (
        control / "minecraft-serverpack-migration.json",
        control / ".minecraft-serverpack-migration.json.tmp",
        control / "minecraft-serverpack-archive-checkpoint.json",
        control / ".minecraft-serverpack-archive-checkpoint.tmp",
        root / "runtime.migration-stage",
        root / "runtime.migration-rollback",
        root / "runtime.migration-failed",
    )
    for entry in entries:
        if entry.is_symlink() or entry.exists():
            raise MinecraftServerPackPreflightError(
                "previous Server Pack migration requires explicit finalization or recovery"
            )
