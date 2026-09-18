#!/usr/bin/env python3
"""Steam Workshop acquisition capability for the Linux Agent.

The Controller only supplies typed artifact identity. Authentication is resolved
locally from the Agent session/environment and SteamCMD is executed without a
shell. Activation remains owned by content_client.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from content_provider import register_provider
from game_data_executor import _steamcmd

_PACKAGE = re.compile(r"^(?P<app>[0-9]+):(?P<item>[0-9]+)$")
_REVISION = re.compile(r"^[0-9]{1,20}$")
_TIMEOUT_SECONDS = 7200
_DEFAULT_RETENTION = 0


def _retention_limit() -> int | None:
    raw = str(os.environ.get("CAPIVARA_WORKSHOP_CACHE_REVISIONS", _DEFAULT_RETENTION)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _DEFAULT_RETENTION
    if value <= 0:
        return None
    return max(2, min(value, 20))


def _prune_revision_cache(revisions_root: Path, *, keep_revision: str) -> list[str]:
    if not revisions_root.is_dir():
        return []
    candidates = [
        path
        for path in revisions_root.iterdir()
        if path.is_dir() and _REVISION.fullmatch(path.name)
    ]
    candidates.sort(key=lambda path: int(path.name), reverse=True)
    limit = _retention_limit()
    if limit is None:
        return []

    keep = {keep_revision}
    for path in candidates:
        if len(keep) >= limit:
            break
        keep.add(path.name)

    removed: list[str] = []
    for path in candidates:
        if path.name in keep:
            continue
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


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


def _revision(artifact: dict[str, Any]) -> str | None:
    value = str(artifact.get("revision") or "").strip()
    if not value:
        return None
    if not _REVISION.fullmatch(value):
        raise ValueError("Steam Workshop revision must be numeric")
    return value


def _revision_cache_path(
    game_data_root: Path,
    app_id: str,
    item_id: str,
    revision: str,
) -> Path:
    state_root = Path(game_data_root).resolve().parent
    return (
        state_root
        / "provider-cache"
        / "steam-workshop"
        / app_id
        / item_id
        / "revisions"
        / revision
    ).resolve()


def _snapshot_revision(
    source: Path,
    game_data_root: Path,
    app_id: str,
    item_id: str,
    revision: str,
) -> Path:
    destination = _revision_cache_path(
        game_data_root,
        app_id,
        item_id,
        revision,
    )
    if destination.is_dir():
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{revision}.{os.getpid()}.tmp"
    if temporary.exists():
        shutil.rmtree(temporary, ignore_errors=True)
    try:
        shutil.copytree(source, temporary)
        if destination.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        else:
            os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    if not destination.is_dir():
        raise RuntimeError("Steam Workshop revision cache materialization failed")
    _prune_revision_cache(destination.parent, keep_revision=revision)
    return destination


def _cache_candidates(executable: str, game_data_root: Path, app_id: str, item_id: str) -> list[Path]:
    state_root = Path(game_data_root).resolve().parent
    home = Path(os.environ.get("HOME") or str(state_root)).resolve()
    suffix = Path("steamapps") / "workshop" / "content" / app_id / item_id
    executable_dir = Path(executable).resolve().parent
    candidates = [
        executable_dir / suffix,
        executable_dir.parent / suffix,
        state_root / "tools" / "steamcmd" / suffix,
        home / ".steam" / "steam" / suffix,
        home / ".local" / "share" / "Steam" / suffix,
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
    revision = _revision(artifact)
    if revision:
        cached = _revision_cache_path(game_data_root, app_id, item_id, revision)
        if cached.is_dir():
            return cached

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
            if revision:
                return _snapshot_revision(
                    candidate,
                    game_data_root,
                    app_id,
                    item_id,
                    revision,
                )
            return candidate
    raise RuntimeError("SteamCMD completed but the Workshop item was not found in a managed Steam cache")


# `steam-workshop` is canonical. `steam` remains accepted for previously stored
# Workshop assignments while callers migrate to the explicit provider name.
register_provider("steam-workshop", resolve_steam_workshop)
register_provider("steam", resolve_steam_workshop)

__all__ = ["resolve_steam_workshop"]
