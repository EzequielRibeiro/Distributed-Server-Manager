#!/usr/bin/env python3
"""Detect primitive execution capabilities on Windows Agents."""
from __future__ import annotations
import os,shutil
from pathlib import Path
def _managed_steamcmd()->Path:
 return Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")/"CapivaraAgent"/"tools"/"steamcmd"/"steamcmd.exe"
def detect_capabilities()->dict[str,bool]:
 steamcmd=shutil.which("steamcmd.exe") is not None or shutil.which("steamcmd") is not None or _managed_steamcmd().is_file()
 return {"native-windows":True,"powershell":shutil.which("powershell") is not None or shutil.which("pwsh") is not None,"steamcmd":steamcmd,"java":shutil.which("java.exe") is not None or shutil.which("java") is not None,"docker":shutil.which("docker.exe") is not None or shutil.which("docker") is not None,"wine":False,"backup":True,"mod-management":True}
__all__=["detect_capabilities"]
