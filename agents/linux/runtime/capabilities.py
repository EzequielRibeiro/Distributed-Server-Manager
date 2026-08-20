#!/usr/bin/env python3
"""Detect execution capabilities available on a Linux Agent host."""

from __future__ import annotations

import shutil
from pathlib import Path


def detect_capabilities() -> dict[str, bool]:
    """Return factual host/runtime capabilities suitable for placement."""
    steamcmd = shutil.which("steamcmd") is not None or Path("/usr/games/steamcmd").exists()
    java = shutil.which("java") is not None
    docker = shutil.which("docker") is not None
    wine = shutil.which("wine") is not None or shutil.which("wine64") is not None

    return {
        "native-linux": True,
        "systemd": Path("/run/systemd/system").exists(),
        "steamcmd": steamcmd,
        "docker": docker,
        "wine": wine,
        "minecraft-java": java,
        # Bedrock is native Linux and does not require Java; this indicates the
        # Agent runtime can host the Linux Bedrock server package.
        "minecraft-bedrock": True,
        # DayZ Linux server installation/runtime requires SteamCMD in the
        # current Capivara adapter contract.
        "dayz": steamcmd,
        # These are runtime management abilities delivered by the Agent model,
        # not assumptions about a particular game installation.
        "backup": True,
        "mod-management": True,
    }


__all__ = ["detect_capabilities"]
