#!/usr/bin/env python3
"""Detect primitive execution capabilities available on a Linux Agent host."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import platform
from pathlib import Path


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
    java = shutil.which("java") is not None
    docker = shutil.which("docker") is not None
    wine = shutil.which("wine") is not None or shutil.which("wine64") is not None

    return {
        "native-linux": True,
        "systemd": Path("/run/systemd/system").exists(),
        "steamcmd": bool(steamcmd_status["functional"]),
        "steamcmd_status": steamcmd_status,
        "prerequisites": {
            "steamcmd_runtime": "ready" if steamcmd_status.get("runtime_32bit") else "missing",
            "java_runtime": "ready" if java else "missing",
            "container_runtime": "ready" if docker else "missing",
            "wine_runtime": "ready" if wine else "missing",
        },
        "java": java,
        "docker": docker,
        "wine": wine,
        # These keys belong to the capability vocabulary but remain false until
        # the remote Agent runtime exposes the corresponding command surfaces.
        "backup": False,
        "mod-management": False,
    }


__all__ = ["detect_capabilities"]
