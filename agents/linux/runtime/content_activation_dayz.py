#!/usr/bin/env python3
"""Safe DayZ Universal Content activation primitives.

DayZ mods may only be activated from an instance-scoped managed content root.
Workshop public keys are discovered by the Agent and projected into an atomic,
instance-private keyring that systemd bind-mounts over the shared server keys
path for that one process namespace.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any

_MAX_KEYS = 512
_MAX_KEY_BYTES = 2 * 1024 * 1024
_DAYZ_WORKSHOP_PACKAGE = re.compile(r"^221100:([1-9][0-9]{0,19})$")
_ALIAS_PREFIX = "@dsm-"


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


def _managed_roots(spec: dict[str, Any]) -> list[Path]:
    roots: list[Path] = []
    state = str(spec.get("instance_state_root") or "").strip()
    if state and os.path.isabs(state):
        roots.append((Path(state).resolve(strict=False) / "content").resolve(strict=False))
    iid = str(spec.get("instance_id") or "").strip()
    working = str(spec.get("working_directory") or spec.get("path") or "").strip()
    if iid and working and os.path.isabs(working):
        roots.append((Path(working).resolve(strict=False) / "content" / "instances" / iid).resolve(strict=False))
    if not roots:
        raise DayZContentActivationError("DayZ content requires instance-scoped runtime roots")
    return roots


def _managed_path(spec: dict[str, Any], entry: dict[str, Any]) -> Path:
    value = str(entry.get("managed_path") or "").strip()
    if not value or not os.path.isabs(value) or any(ch in value for ch in ("\x00", "\r", "\n", ";")):
        raise DayZContentActivationError("invalid DayZ managed content path")
    path = Path(value).resolve(strict=False)
    accepted = False
    for root in _managed_roots(spec):
        try:
            path.relative_to(root)
            accepted = True
            break
        except ValueError:
            continue
    if not accepted:
        raise DayZContentActivationError("DayZ managed path is not instance-scoped")
    if _is_link(path) or not path.is_dir():
        raise DayZContentActivationError("DayZ managed content is unavailable or linked")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workshop_alias(spec: dict[str, Any], entry: dict[str, Any], source: Path) -> tuple[str, str]:
    package_id = str(entry.get("package_id") or "").strip()
    match = _DAYZ_WORKSHOP_PACKAGE.fullmatch(package_id)
    if not match:
        raise DayZContentActivationError("DayZ Workshop content requires canonical package_id 221100:<id>")
    working_text = str(spec.get("working_directory") or spec.get("path") or "").strip()
    instance_id = str(spec.get("instance_id") or "").strip()
    if not working_text or not os.path.isabs(working_text):
        raise DayZContentActivationError("DayZ Workshop aliases require an absolute working_directory")
    if not instance_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in instance_id):
        raise DayZContentActivationError("DayZ Workshop aliases require a safe instance_id")
    alias = f"{_ALIAS_PREFIX}{instance_id}-{match.group(1)}"
    if len(alias.encode("utf-8")) > 255:
        raise DayZContentActivationError("DayZ Workshop alias exceeds filesystem name limit")
    target = Path(working_text).resolve(strict=False) / alias
    return alias, str(target)


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
    aliases: dict[str, dict[str, str]] = {}
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
        alias, target = _workshop_alias(spec, entry, path)
        current_alias = aliases.get(alias.casefold())
        if current_alias and current_alias["source"] != str(path):
            raise DayZContentActivationError("conflicting DayZ Workshop alias")
        aliases[alias.casefold()] = {"alias": alias, "source": str(path), "target": target}
        seen_paths[identity] = mode
        (mods if mode == "mod" else server_mods).append(alias)
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
    return {
        "arguments": arguments,
        "aliases": [aliases[name] for name in sorted(aliases)],
        "key_sources": [keys[name] for name in sorted(keys)],
    }


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
    state_text = str(spec.get("instance_state_root") or "").strip()
    working_text = str(spec.get("working_directory") or "").strip()
    if not state_text or not working_text or not os.path.isabs(state_text) or not os.path.isabs(working_text):
        raise DayZContentActivationError("DayZ keyring requires absolute runtime roots")
    state_root = Path(state_text).resolve(strict=False)
    working_root = Path(working_text).resolve(strict=False)
    keyring = _within(state_root, Path(str(spec.get("content_dayz_keyring") or state_root / ".dsm/dayz-keys")), "DayZ keyring")
    base_root = _within(working_root, Path(str(spec.get("content_dayz_base_keys_root") or working_root / "keys")), "DayZ base keys")
    combined: dict[str, dict[str, str]] = {}
    total_bytes = 0
    for item in [*_collect_base_keys(base_root), *[dict(value) for value in sources if isinstance(value, dict)]]:
        source = Path(str(item.get("source") or ""))
        name = str(item.get("name") or source.name)
        expected = str(item.get("sha256") or "").lower()
        if not source.is_absolute() or Path(name).name != name or source.suffix.casefold() != ".bikey" or Path(name).suffix.casefold() != ".bikey":
            raise DayZContentActivationError("invalid DayZ signature key source")
        if _is_link(source) or not source.is_file():
            raise DayZContentActivationError("DayZ signature key source is unavailable or linked")
        size = source.stat().st_size
        if size < 0 or size > _MAX_KEY_BYTES:
            raise DayZContentActivationError("DayZ signature key exceeds safety limit")
        actual = _sha256(source)
        if expected and expected != actual:
            raise DayZContentActivationError("DayZ signature key changed after discovery")
        folded = name.casefold()
        current = combined.get(folded)
        if current and current["sha256"] != actual:
            raise DayZContentActivationError(f"conflicting DayZ signature key: {name}")
        if not current:
            total_bytes += size
            if total_bytes > _MAX_KEY_BYTES:
                raise DayZContentActivationError("DayZ signature keyring exceeds safety limit")
            combined[folded] = {"source": str(source), "name": name, "sha256": actual}
    if len(combined) > _MAX_KEYS:
        raise DayZContentActivationError("DayZ signature keyring has too many entries")
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
            shutil.copyfile(item["source"], target)
            os.chmod(target, 0o644)
            if _sha256(target) != item["sha256"]:
                raise DayZContentActivationError("DayZ signature key changed while materializing keyring")
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
