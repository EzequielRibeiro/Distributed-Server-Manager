#!/usr/bin/env python3
"""Steam Workshop acquisition capability for the Linux Agent.

The Controller only supplies typed artifact identity. Authentication is resolved
locally from the Agent session/environment and SteamCMD is executed without a
shell. Activation remains owned by content_client.
"""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from content_provider import register_provider
from content_cache_inventory import record_cache_event
from content_update_provider import parse_workshop_manifest
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


def _prune_revision_cache(
    revisions_root: Path,
    *,
    keep_revision: str,
    protected_revisions: set[str] | None = None,
) -> list[str]:
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

    protected = set(protected_revisions or ())
    protected.add(keep_revision)
    keep = set(protected)
    for path in candidates:
        if path.name in keep:
            continue
        if len(keep - protected) >= limit:
            break
        keep.add(path.name)

    removed: list[str] = []
    for path in candidates:
        if path.name in keep:
            continue
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def _protected_revisions(artifact: dict[str, Any]) -> set[str]:
    raw = artifact.get("protected_revisions")
    if raw is None:
        return set()
    if not isinstance(raw, list):
        raise ValueError("Steam Workshop protected_revisions must be a list")
    protected: set[str] = set()
    for value in raw[:500]:
        revision = str(value or "").strip()
        if not _REVISION.fullmatch(revision):
            raise ValueError("Steam Workshop protected revision must be numeric")
        protected.add(revision)
    return protected


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


def _revision_lock_path(
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
        / "locks"
        / f"{revision}.lock"
    ).resolve()


class _RevisionLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle is not None:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            finally:
                self.handle.close()
        return False


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
    protected_revisions: set[str] | None = None,
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
    _prune_revision_cache(
        destination.parent,
        keep_revision=revision,
        protected_revisions=protected_revisions,
    )
    return destination


def _validate_revision_source(source: Path, app_id: str, item_id: str, revision: str) -> None:
    manifest = source.parent.parent.parent / f"appworkshop_{app_id}.acf"
    try:
        text = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError("Steam Workshop revision manifest is unavailable") from exc
    installed = parse_workshop_manifest(text, item_id)
    if not installed:
        raise RuntimeError("Steam Workshop revision metadata is unavailable")
    if installed != revision:
        raise RuntimeError(
            f"Steam Workshop revision mismatch: requested {revision}, installed {installed}"
        )


def _cache_candidates(executable: str, game_data_root: Path, app_id: str, item_id: str) -> list[Path]:
    state_root = Path(game_data_root).resolve().parent
    agent_state_root = Path(
        os.environ.get("CAPIVARA_AGENT_STATE_DIR") or str(state_root)
    ).resolve()
    home = Path(os.environ.get("HOME") or str(agent_state_root)).resolve()
    dsm_root = Path(os.environ.get("DSM_ROOT") or "/opt/dsm").resolve()
    executable_dir = Path(executable).resolve().parent
    suffix = Path("steamapps") / "workshop" / "content" / app_id / item_id

    # SteamCMD has several Linux layouts depending on whether it comes from the
    # Capivara-managed bootstrap, a distro package, or an existing user Steam
    # installation. Keep discovery bounded to explicit trusted roots instead of
    # scanning the host filesystem.
    roots = [
        executable_dir,
        executable_dir.parent,
        agent_state_root / "tools" / "steamcmd",
        state_root / "tools" / "steamcmd",
        dsm_root / "tools" / "steamcmd",
        home / ".steam" / "steamcmd",
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam" / "steamcmd",
        home / ".local" / "share" / "Steam",
        home / "Steam" / "steamcmd",
        home / "Steam",
    ]
    out: list[Path] = []
    for root in roots:
        candidate = (root / suffix).resolve()
        if candidate not in out:
            out.append(candidate)
    return out


def _download_and_resolve(
    artifact: dict[str, Any],
    game_data_root: Path,
    app_id: str,
    item_id: str,
    revision: str | None,
    protected_revisions: set[str],
) -> Path:
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
    revision_errors: list[str] = []
    for candidate in _cache_candidates(executable, game_data_root, app_id, item_id):
        if not candidate.is_dir():
            continue
        if revision:
            try:
                _validate_revision_source(candidate, app_id, item_id, revision)
            except RuntimeError as exc:
                revision_errors.append(str(exc))
                continue
            return _snapshot_revision(
                candidate,
                game_data_root,
                app_id,
                item_id,
                revision,
                protected_revisions,
            )
        return candidate
    if revision_errors:
        raise RuntimeError(
            "SteamCMD completed but no managed Workshop cache matched the requested revision: "
            + "; ".join(revision_errors[:3])
        )
    raise RuntimeError("SteamCMD completed but the Workshop item was not found in a managed Steam cache")


def resolve_steam_workshop(artifact: dict[str, Any], stage: Path, game_data_root: Path) -> Path:
    del stage
    app_id, item_id = _identity(artifact)
    revision = _revision(artifact)
    protected_revisions = _protected_revisions(artifact)
    if not revision:
        return _download_and_resolve(
            artifact,
            game_data_root,
            app_id,
            item_id,
            None,
            protected_revisions,
        )

    cached = _revision_cache_path(game_data_root, app_id, item_id, revision)
    if cached.is_dir():
        record_cache_event("hit")
        return cached

    lock_path = _revision_lock_path(game_data_root, app_id, item_id, revision)
    with _RevisionLock(lock_path):
        if cached.is_dir():
            record_cache_event("hit")
            return cached
        record_cache_event("miss")
        result = _download_and_resolve(
            artifact,
            game_data_root,
            app_id,
            item_id,
            revision,
            protected_revisions,
        )
        record_cache_event("download")
        return result


# `steam-workshop` is canonical. `steam` remains accepted for previously stored
# Workshop assignments while callers migrate to the explicit provider name.
register_provider("steam-workshop", resolve_steam_workshop)
register_provider("steam", resolve_steam_workshop)

__all__ = ["resolve_steam_workshop"]
