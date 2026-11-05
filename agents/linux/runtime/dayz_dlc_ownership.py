"""Discover candidate official DayZ DLC trees without trusting names or symlinks.

A top-level directory with addons/*.pbo is a candidate, not proof of
Bohemia provenance. Limit scans to controlled Steam install roots.
"""
from __future__ import annotations

import os
from pathlib import Path

_RESERVED = frozenset({
    "addons", "dta", "docs", "mpmissions", "battleye", "keys",
    "steamapps", "server_manager", "profiles", "config",
})


def discover_dayz_dlc_paths(root: Path) -> list[Path]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("DayZ content root must be a real directory")
    candidates: list[list[Path]] = []
    for dlc in root.iterdir():
        name = dlc.name
        if name.lower() in _RESERVED or name.startswith(("@", ".")):
            continue
        if dlc.is_symlink():
            raise ValueError("DayZ content root contains a symlink")
        if not dlc.is_dir():
            continue
        if (dlc / "mod.cpp").exists() or (dlc / "meta.cpp").exists():
            continue
        addons = dlc / "addons"
        if addons.is_symlink():
            raise ValueError("DayZ DLC addons must not be a symlink")
        if not addons.is_dir():
            continue
        if not any(child.is_file() and not child.is_symlink() and child.suffix.lower() == ".pbo"
                   for child in addons.iterdir()):
            continue
        paths = [dlc]
        for directory, directories, files in os.walk(dlc, followlinks=False):
            for entry in directories + files:
                path = Path(directory) / entry
                if path.is_symlink():
                    raise ValueError("DayZ DLC contains a symlink")
                paths.append(path)
        candidates.append(paths)
    return [p for paths in candidates for p in paths]
