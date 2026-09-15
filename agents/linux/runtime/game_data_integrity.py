#!/usr/bin/env python3
"""Bounded game-data integrity inventory for reconciliation and recovery."""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any

MAX_INVENTORY_FILES = 200000


def inspect_game_data(root: Path, selection: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    if not root.is_dir():
        return {"health": "missing", "exists": False, "files": 0, "bytes": 0}
    digest = hashlib.sha256(); files = 0; total = 0; truncated = False
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            try: path.resolve().relative_to(root)
            except ValueError:
                return {"health": "unsafe", "exists": True, "files": files, "bytes": total, "reason": "symlink_escape"}
            continue
        if not path.is_file():
            continue
        files += 1
        if files > MAX_INVENTORY_FILES:
            truncated = True; break
        stat = path.stat(); total += stat.st_size
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8")); digest.update(b"\0"); digest.update(str(stat.st_size).encode("ascii")); digest.update(b"\n")
    executable = str((selection or {}).get("executable") or "").strip()
    artifact_mode = str((selection or {}).get("artifact_mode") or "executable").strip().lower()
    executable_present = True; executable_ready = True
    if executable:
        candidate = Path(executable)
        candidate = candidate if candidate.is_absolute() else root / candidate
        try:
            candidate.resolve().relative_to(root)
            executable_present = candidate.is_file()
            executable_ready = executable_present and (artifact_mode in {"file","java","jar"} or bool(candidate.stat().st_mode & 0o100))
        except ValueError:
            executable_present = False; executable_ready = False
    health = "ok" if files and executable_present and executable_ready and not truncated else ("degraded" if files else "empty")
    return {"health": health, "exists": True, "files": min(files, MAX_INVENTORY_FILES), "bytes": total, "tree_digest": digest.hexdigest(), "truncated": truncated, "executable_present": executable_present, "executable_ready": executable_ready}


def should_repair(integrity: dict[str, Any]) -> bool:
    return str(integrity.get("health") or "") not in {"ok"}

__all__ = ["MAX_INVENTORY_FILES", "inspect_game_data", "should_repair"]
