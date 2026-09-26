#!/usr/bin/env python3
"""Safe discovery helpers for community DayZ mission payloads."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_SAFE_MISSION = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MAX_MISSIONS = 64
_MAX_DEPTH = 8


class DayZCommunityMissionError(ValueError):
    pass


def _is_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        checker = getattr(path, "is_junction", None)
        return bool(checker and checker())
    except OSError:
        return True


def _within(root: Path, value: Path) -> Path:
    root = root.resolve(strict=False)
    path = value.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DayZCommunityMissionError("DayZ community mission escapes payload root") from exc
    return path


def _relative_depth(root: Path, path: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return _MAX_DEPTH + 1


def _looks_like_mission(path: Path) -> bool:
    if not path.is_dir() or _is_link(path):
        return False
    init = path / "init.c"
    if not init.is_file() or _is_link(init):
        return False
    economy = path / "cfgeconomycore.xml"
    types = path / "db" / "types.xml"
    return (
        (economy.is_file() and not _is_link(economy))
        or (types.is_file() and not _is_link(types))
    )


def discover_community_missions(root: Path | str) -> list[dict[str, Any]]:
    payload = Path(root).resolve(strict=False)
    if not payload.is_dir() or _is_link(payload):
        raise DayZCommunityMissionError("DayZ community map payload is not a safe directory")

    found: dict[str, Path] = {}
    for current, directories, _files in os.walk(payload, followlinks=False):
        base = Path(current)
        if _relative_depth(payload, base) > _MAX_DEPTH:
            directories[:] = []
            continue

        clean_directories: list[str] = []
        for name in directories:
            child = base / name
            if _is_link(child):
                raise DayZCommunityMissionError("DayZ community map payload contains a symbolic link")
            clean_directories.append(name)
        directories[:] = clean_directories

        if base == payload or not _looks_like_mission(base):
            continue

        name = base.name
        if not _SAFE_MISSION.fullmatch(name):
            raise DayZCommunityMissionError(f"invalid DayZ community mission name: {name}")

        resolved = _within(payload, base)
        folded = name.casefold()
        previous = found.get(folded)
        if previous is not None and previous != resolved:
            raise DayZCommunityMissionError(f"duplicate DayZ community mission name: {name}")
        found[folded] = resolved

        if len(found) > _MAX_MISSIONS:
            raise DayZCommunityMissionError("DayZ community map payload exposes too many missions")

    if not found:
        raise DayZCommunityMissionError(
            "DayZ community map payload contains no recognizable mission directories"
        )

    result: list[dict[str, Any]] = []
    for key in sorted(found):
        path = found[key]
        result.append({
            "id": path.name,
            "relative_path": path.relative_to(payload).as_posix(),
            "source": "community-content",
        })
    return result


def community_mission_manifest(root: Path | str) -> dict[str, Any]:
    missions = discover_community_missions(root)
    return {
        "schema_version": 1,
        "kind": "CapivaraDayZCommunityMissionManifest",
        "missions": missions,
        "count": len(missions),
    }


__all__ = [
    "DayZCommunityMissionError",
    "community_mission_manifest",
    "discover_community_missions",
]
