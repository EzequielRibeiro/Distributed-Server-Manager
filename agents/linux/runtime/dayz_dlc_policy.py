"""Explicit, fail-safe registry of independently licensed DayZ content roots.

Unknown Steam directories are never classified as DLC automatically.
"""
from pathlib import Path

# A future DLC needs a reviewed registry entry and a mission-to-content mapping.
DLC_MISSIONS = {"nasdara": frozenset({"nasdara"})}


def inaccessible_dlc_paths(install_root: str, mission: str) -> list[str]:
    root = Path(install_root)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("invalid DayZ install root")
    suffix = str(mission).lower().rsplit(".", 1)[-1]
    return [str(root / directory) for directory, missions in sorted(DLC_MISSIONS.items()) if suffix not in missions]

[executed on device: horizon-server (6a5de904-6702-4c4d-8ea8-2c686f883437)]