#!/usr/bin/env python3
"""Safe DayZ Universal Content activation primitives."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

_MAX_KEYS = 512
_MAX_KEY_BYTES = 2 * 1024 * 1024


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
        raise DayZContentActivationError(f"{label} escapes its allowed root") from exc
    return path


def _managed_root(spec: dict[str, Any]) -> Path:
    iid = str(spec.get("instance_id") or "").strip()
    working = str(spec.get("working_directory") or spec.get("path") or "").strip()
    if not iid or not working or not os.path.isabs(working):
        raise DayZContentActivationError("DayZ content requires instance and runtime roots")
    return (Path(working).resolve(strict=False) / "content" / "instances" / iid).resolve(strict=False)


def _managed_path(spec: dict[str, Any], entry: dict[str, Any]) -> Path:
    value = str(entry.get("managed_path") or "").strip()
    if not value or not os.path.isabs(value) or any(ch in value for ch in ("\x00", "\r", "\n", ";")):
        raise DayZContentActivationError("invalid DayZ managed content path")
    path = _within(_managed_root(spec), Path(value), "DayZ managed path")
    if _is_link(path) or not path.is_dir():
        raise DayZContentActivationError("DayZ managed content is unavailable or linked")
    return path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _base_keys(spec: dict[str, Any]) -> list[dict[str, str]]:
    working = Path(str(spec.get("working_directory") or spec.get("path") or "")).resolve(strict=False)
    root = _within(working, working / "keys", "DayZ base keys")
    if not root.exists():
        return []
    if _is_link(root) or not root.is_dir():
        raise DayZContentActivationError("DayZ base keys directory is unsafe")
    values: list[dict[str, str]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if path.suffix.casefold() != ".bikey":
            continue
        if _is_link(path) or not path.is_file():
            raise DayZContentActivationError("DayZ base signature key is unsafe")
        values.append({"source": str(path.resolve()), "name": path.name, "sha256": _sha256(path)})
    return values


def build_dayz_key_bundle(spec: dict[str, Any], mod_keys: list[dict[str, str]]) -> str:
    combined: dict[str, dict[str, str]] = {}
    total = 0
    for raw in [*_base_keys(spec), *[dict(item) for item in mod_keys if isinstance(item, dict)]]:
        source = Path(str(raw.get("source") or ""))
        name = str(raw.get("name") or source.name)
        expected = str(raw.get("sha256") or "").strip().lower()
        if not source.is_absolute() or source.suffix.casefold() != ".bikey" or _is_link(source) or not source.is_file():
            raise DayZContentActivationError("invalid DayZ signature key source")
        if Path(name).name != name or not name or Path(name).suffix.casefold() != ".bikey":
            raise DayZContentActivationError("invalid DayZ signature key name")
        data = source.read_bytes()
        total += len(data)
        if total > _MAX_KEY_BYTES:
            raise DayZContentActivationError("DayZ signature key bundle exceeds safety limit")
        actual = _sha256_bytes(data)
        if expected and expected != actual:
            raise DayZContentActivationError("DayZ signature key changed after discovery")
        folded = name.casefold()
        current = combined.get(folded)
        if current and current["sha256"] != actual:
            raise DayZContentActivationError(f"conflicting DayZ signature key: {name}")
        combined.setdefault(folded, {"name": name, "sha256": actual, "data": base64.b64encode(data).decode("ascii")})
    if len(combined) > _MAX_KEYS:
        raise DayZContentActivationError("DayZ signature key bundle has too many entries")
    return json.dumps([combined[name] for name in sorted(combined)], separators=(",", ":"), sort_keys=True)


__all__ = ["DayZContentActivationError", "build_dayz_key_bundle", "project_dayz_activation"]
