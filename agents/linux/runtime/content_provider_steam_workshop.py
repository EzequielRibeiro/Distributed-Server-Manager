#!/usr/bin/env python3
"""Steam Workshop acquisition capability for the Linux Agent.

The Controller only supplies typed artifact identity. Authentication is resolved
locally from the Agent session/environment and SteamCMD is executed without a
shell. Activation remains owned by content_client.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from content_provider import register_provider
from game_data_executor import _steamcmd

_PACKAGE = re.compile(r"^(?P<app>[0-9]+):(?P<item>[0-9]+)$")
_TIMEOUT_SECONDS = 7200


def _identity(artifact: dict[str, Any]) -> tuple[str, str]:
    package = str(artifact.get("package_id") or "").strip()
    match = _PACKAGE.fullmatch(package)
    if not match:
        raise ValueError("Steam Workshop package_id must be APP_ID:PUBLISHED_FILE_ID")
    return match.group("app"), match.group("item")


def _login(artifact: dict[str, Any]) -> str:
    auth = str(artifact.get("auth") or "anonymous").strip().lower()
    if auth in {"", "anonymous"}:
        return "anonymous"
    user = str(os.environ.get("DSM_STEAM_USER") or "").strip()
    if not user:
        raise RuntimeError("Steam authentication is required on this Agent")
    return user


def _cache_candidates(executable: str, game_data_root: Path, app_id: str, item_id: str) -> list[Path]:
    state_root = Path(game_data_root).resolve().parent
    home = Path(os.environ.get("HOME") or str(state_root)).resolve()
    suffix = Path("steamapps") / "workshop" / "content" / app_id / item_id
    candidates = [
        Path(executable).resolve().parent / suffix,
        state_root / "tools" / "steamcmd" / suffix,
        home / ".steam" / "steam" / suffix,
        home / "Steam" / suffix,
    ]
    out: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in out:
            out.append(resolved)
    return out


def resolve_steam_workshop(artifact: dict[str, Any], stage: Path, game_data_root: Path) -> Path:
    del stage
    app_id, item_id = _identity(artifact)
    executable = _steamcmd()
    login = _login(artifact)
    env = {**os.environ, "HOME": os.environ.get("HOME", str(Path(game_data_root).resolve().parent))}
    completed = subprocess.run(
        [executable, "+login", login, "+workshop_download_item", app_id, item_id, "validate", "+quit"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        output = (completed.stdout or "").lower()
        if "password" in output or "steam guard" in output or "two-factor" in output:
            raise RuntimeError("Steam authentication is required or expired on this Agent")
        raise RuntimeError(f"Steam Workshop download failed with exit code {completed.returncode}")
    for candidate in _cache_candidates(executable, game_data_root, app_id, item_id):
        if candidate.is_dir():
            return candidate
    raise RuntimeError("SteamCMD completed but the Workshop item was not found in a managed Steam cache")


# `steam-workshop` is canonical. `steam` remains accepted for previously stored
# Workshop assignments while callers migrate to the explicit provider name.
register_provider("steam-workshop", resolve_steam_workshop)
register_provider("steam", resolve_steam_workshop)

__all__ = ["resolve_steam_workshop"]
