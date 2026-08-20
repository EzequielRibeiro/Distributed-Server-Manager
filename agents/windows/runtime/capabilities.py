#!/usr/bin/env python3
"""Detect primitive execution capabilities on Windows Agents."""

from __future__ import annotations

import shutil


def detect_capabilities() -> dict[str, bool]:
    return {
        "native-windows": True,
        "powershell": shutil.which("powershell") is not None or shutil.which("pwsh") is not None,
        "steamcmd": shutil.which("steamcmd.exe") is not None,
        "java": shutil.which("java.exe") is not None,
        "docker": shutil.which("docker.exe") is not None,
        "wine": False,
        "backup": False,
        "mod-management": False,
    }


__all__ = ["detect_capabilities"]
