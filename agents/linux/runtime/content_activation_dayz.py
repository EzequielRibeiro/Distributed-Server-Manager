#!/usr/bin/env python3
"""Safe DayZ Universal Content activation primitives.

Only Agent-observed managed paths are accepted. Workshop keys are discovered from
managed content and can be projected into an instance-private keyring by callers.
"""
from __future__ import annotations

import hashlib
import os
import shutil
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


def _collect_base_keys(root: Path) -> list[dict[str, str]]:
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


def materialize_dayz_keyring(spec: dict[str, Any]) -> list[str]:
    sources = spec.get("content_dayz_key_sources")
    if not isinstance(sources, list) or not sources:
        return []
    state_root = Path(str(spec.get("instance_state_root") or "")).resolve(strict=False)
    working_root = Path(str(spec.get("working_directory") or "")).resolve(strict=False)
    if not str(state_root) or not str(working_root):
        raise DayZContentActivationError("DayZ keyring requires runtime roots")
    keyring = _within(state_root, Path(str(spec.get("content_dayz_keyring") or state_root / ".dsm/dayz-keys")), "DayZ keyring")
    base_root = _within(working_root, Path(str(spec.get("content_dayz_base_keys_root") or working_root / "keys")), "DayZ base keys")
    combined: dict[str, dict[str, str]] = {}
    for item in [*_collect_base_keys(base_root), *[dict(value) for value in sources if isinstance(value, dict)]]:
        source = Path(str(item.get("source") or ""))
        name = str(item.get("name") or source.name)
        expected = str(item.get("sha256") or "").lower()
        if not source.is_absolute() or source.suffix.casefold() != ".bikey" or _is_link(source) or not source.is_file():
            raise DayZContentActivationError("invalid DayZ signature key source")
        actual = _sha256(source)
        if expected and expected != actual:
            raise DayZContentActivationError("DayZ signature key changed after projection")
        folded = name.casefold()
        current = combined.get(folded)
        if current and current["sha256"] != actual:
            raise DayZContentActivationError(f"conflicting DayZ signature key: {name}")
        combined.setdefault(folded, {"source": str(source), "name": name, "sha256": actual})
    keyring.parent.mkdir(parents=True, exist_ok=True)
    staging = keyring.with_name(f".{keyring.name}.{os.getpid()}.tmp")
    backup = keyring.with_name(f".{keyring.name}.{os.getpid()}.old")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    staging.mkdir(mode=0o755)
    try:
        written: list[str] = []
        for item in combined.values():
            target = staging / item["name"]
            shutil.copy2(item["source"], target)
            os.chmod(target, 0o644)
            written.append(str(Path(".dsm/dayz-keys") / item["name"]))
        if keyring.exists():
            if _is_link(keyring) or not keyring.is_dir():
                raise DayZContentActivationError("existing DayZ keyring is unsafe")
            os.replace(keyring, backup)
        os.replace(staging, keyring)
        shutil.rmtree(backup, ignore_errors=True)
        return written
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not keyring.exists():
            os.replace(backup, keyring)
        raise


__all__ = ["DayZContentActivationError", "materialize_dayz_keyring", "project_dayz_activation"]
