#!/usr/bin/env python3
"""Safe DayZ Universal Content activation primitives.

Only Agent-observed managed paths are accepted. Workshop keys are discovered from
managed content so Windows can fail closed when no per-instance key isolation exists.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

_MAX_KEYS = 512


class DayZContentActivationError(RuntimeError):
    pass


def _is_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        checker = getattr(path, "is_junction", None)
        return bool(checker and checker())
    except OSError:
        return True


def _within(root: Path, value: Path, label: str) -> Path:
    root = root.resolve(strict=False)
    path = value.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DayZContentActivationError(f"{label} escapes managed instance content") from exc
    return path


def _managed_path(spec: dict[str, Any], entry: dict[str, Any]) -> Path:
    state = str(spec.get("instance_state_root") or "").strip()
    value = str(entry.get("managed_path") or "").strip()
    if not state or not value or not os.path.isabs(value):
        raise DayZContentActivationError("DayZ content requires an absolute Agent-managed path")
    if any(ch in value for ch in ("\x00", "\r", "\n", ";")):
        raise DayZContentActivationError("invalid DayZ managed content path")
    root = Path(state).resolve(strict=False) / "content"
    path = _within(root, Path(value), "DayZ managed path")
    if _is_link(path) or not path.is_dir():
        raise DayZContentActivationError("DayZ managed content is unavailable or linked")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _discover_bikeys(root: Path) -> list[dict[str, str]]:
    candidates: list[Path] = []
    try:
        children = list(root.iterdir())
    except OSError as exc:
        raise DayZContentActivationError(f"cannot inspect DayZ mod: {exc}") from exc
    for child in children:
        if child.is_file() and child.suffix.casefold() == ".bikey":
            candidates.append(child)
        elif child.is_dir() and child.name.casefold() == "keys":
            if _is_link(child):
                raise DayZContentActivationError("DayZ mod keys directory cannot be linked")
            for key in child.iterdir():
                if key.is_file() and key.suffix.casefold() == ".bikey":
                    candidates.append(key)
    if len(candidates) > _MAX_KEYS:
        raise DayZContentActivationError("DayZ mod exposes too many signature keys")
    result: list[dict[str, str]] = []
    for key in sorted(candidates, key=lambda item: item.name.casefold()):
        if _is_link(key) or not key.is_file():
            raise DayZContentActivationError("DayZ signature key must be a regular file")
        resolved = _within(root, key, "DayZ signature key")
        result.append({"source": str(resolved), "name": key.name, "sha256": _sha256(resolved)})
    return result


def project_dayz_activation(spec: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    mods: list[str] = []
    server_mods: list[str] = []
    seen_paths: dict[str, str] = {}
    keys: dict[str, dict[str, str]] = {}
    for entry in entries:
        mode = str((entry.get("activation") or {}).get("mode") or "mod").strip().lower()
        if mode not in {"mod", "server-mod"}:
            raise DayZContentActivationError("unsupported DayZ content activation mode")
        path = _managed_path(spec, entry)
        identity = os.path.normcase(str(path))
        previous = seen_paths.get(identity)
        if previous and previous != mode:
            raise DayZContentActivationError("the same DayZ mod cannot be client and server-only simultaneously")
        if previous:
            continue
        seen_paths[identity] = mode
        (mods if mode == "mod" else server_mods).append(str(path))
        for key in _discover_bikeys(path):
            folded = key["name"].casefold()
            current = keys.get(folded)
            if current and current["sha256"] != key["sha256"]:
                raise DayZContentActivationError(f"conflicting DayZ signature key: {key['name']}")
            keys.setdefault(folded, key)
    arguments: list[str] = []
    if mods:
        arguments.append("-mod=" + ";".join(mods))
    if server_mods:
        arguments.append("-serverMod=" + ";".join(server_mods))
    return {"arguments": arguments, "key_sources": [keys[name] for name in sorted(keys)]}


__all__ = ["DayZContentActivationError", "project_dayz_activation"]
