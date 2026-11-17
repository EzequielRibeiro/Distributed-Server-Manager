"""DayZ data files are not equivalent to enabled maps or client DLC requirements.

DayZ may enumerate licensed-content PBOs during signature checks even when a
different map is active. Hiding the directory at the Linux mount namespace
causes false kick 115 (missing PBO) for players without that DLC.

Keep the historical function name for compatibility with existing runtimes,
but do not conceal installed data files. Mission selection stays independent.
"""
from pathlib import Path


def inaccessible_dlc_paths(install_root: str, mission: str) -> list[str]:
    root = Path(install_root)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("invalid DayZ install root")
    return []
