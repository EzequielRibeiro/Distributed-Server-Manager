#!/usr/bin/env python3
"""Detect primitive execution capabilities available on a Linux Agent host."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

_JAVA_VERSION = re.compile(r'version\s+"([^"]+)"', re.IGNORECASE)


def _normalize_architecture(value: str | None = None) -> str:
    machine = str(value or platform.machine() or "").strip().lower()
    aliases = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "i386": "x86_32",
        "i486": "x86_32",
        "i586": "x86_32",
        "i686": "x86_32",
        "x86": "x86_32",
    }
    return aliases.get(machine, machine or "unknown")


def _java_major(version: str) -> int | None:
    token = str(version or "").strip()
    if not token:
        return None
    parts = token.split(".")
    try:
        if parts[0] == "1" and len(parts) > 1:
            return int(parts[1])
        return int(parts[0])
    except ValueError:
        return None


def _java_status() -> dict[str, object]:
    executable = shutil.which("java")
    if not executable:
        return {"installed": False, "functional": False, "state": "missing", "path": None, "version": None, "major": None}
    result: dict[str, object] = {
        "installed": True,
        "functional": False,
        "state": "error",
        "path": executable,
        "version": None,
        "major": None,
    }
    try:
        completed = subprocess.run(
            [executable, "-version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
            check=False,
        )
        output = completed.stdout or ""
        match = _JAVA_VERSION.search(output)
        version = match.group(1) if match else None
        major = _java_major(version or "")
        result.update(
            functional=completed.returncode == 0 and major is not None,
            state="ready" if completed.returncode == 0 and major is not None else "error",
            version=version,
            major=major,
        )
        if not result["functional"]:
            result["error"] = output[-1000:] or f"java -version terminou com código {completed.returncode}"
    except Exception as exc:
        result["error"] = str(exc)[:1000]
    return result


def _steamcmd_status() -> dict[str, object]:
    state_root = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
    managed = state_root / "tools" / "steamcmd" / "steamcmd.sh"
    candidate = shutil.which("steamcmd") or (str(Path("/usr/games/steamcmd")) if Path("/usr/games/steamcmd").is_file() else None)
    path = Path(candidate) if candidate else managed
    loader_candidates = (Path("/lib/ld-linux.so.2"), Path("/lib32/ld-linux.so.2"), Path("/lib/i386-linux-gnu/ld-linux.so.2"))
    runtime_32bit = platform.machine().lower() not in {"x86_64", "amd64"} or any(item.exists() for item in loader_candidates)
    if not path.is_file():
        return {"installed": False, "functional": False, "state": "missing", "path": None, "runtime_32bit": runtime_32bit, "missing_dependencies": [] if runtime_32bit else ["linux-x86-32-runtime"]}

    cache = state_root / "capabilities" / "steamcmd.json"
    try:
        if cache.is_file() and time.time() - cache.stat().st_mtime < 900:
            value = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("schema_version") == 2 and value.get("path") == str(path):
                return value
    except (OSError, ValueError):
        pass

    result: dict[str, object] = {"schema_version": 2, "installed": True, "functional": False, "state": "error", "path": str(path), "runtime_32bit": runtime_32bit, "missing_dependencies": [] if runtime_32bit else ["linux-x86-32-runtime"]}
    if not runtime_32bit:
        result["error"] = "Linux 32-bit runtime is required by SteamCMD"
        return result
    try:
        completed = subprocess.run(
            [str(path), "+quit"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
            env={**os.environ, "HOME": str(state_root)},
        )
        result["functional"] = completed.returncode == 0
        result["state"] = "ready" if completed.returncode == 0 else "error"
        if completed.returncode != 0:
            result["error"] = (completed.stdout or f"SteamCMD terminou com código {completed.returncode}")[-1000:]
    except Exception as exc:
        result["error"] = str(exc)[:1000]
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    return result


def detect_capabilities() -> dict[str, object]:
    """Return factual host/runtime primitives suitable for generic placement."""
    steamcmd_status = _steamcmd_status()
    java_status = _java_status()
    java = bool(java_status["functional"])
    docker = shutil.which("docker") is not None
    wine = shutil.which("wine") is not None or shutil.which("wine64") is not None

    return {
        "platform": {"os": "linux", "architecture": _normalize_architecture()},
        "native-linux": True,
        "systemd": Path("/run/systemd/system").exists(),
        "steamcmd": bool(steamcmd_status["functional"]),
        "steamcmd_status": steamcmd_status,
        "java": java,
        "java_status": java_status,
        "prerequisites": {
            "steamcmd_runtime": "ready" if steamcmd_status.get("runtime_32bit") else "missing",
            "java_runtime": "ready" if java else "missing",
            "container_runtime": "ready" if docker else "missing",
            "wine_runtime": "ready" if wine else "missing",
        },
        "docker": docker,
        "wine": wine,
        # These keys belong to the capability vocabulary but remain false until
        # the remote Agent runtime exposes the corresponding command surfaces.
        "backup": False,
        "mod-management": False,
    }


__all__ = ["detect_capabilities"]
