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
        "minecraft-bedrock": True,
        "dayz": steamcmd,
        # These keys are already part of the capability vocabulary, but remain
        # false until the remote Agent runtime actually exposes those command
        # surfaces. Roadmap intent is never reported as runtime evidence.
        "backup": False,
        "mod-management": False,
    }


__all__ = ["detect_capabilities"]
