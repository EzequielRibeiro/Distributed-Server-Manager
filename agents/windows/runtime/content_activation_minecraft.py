#!/usr/bin/env python3
"""Minecraft adapter for Universal Content activation.

Managed artifacts stay under ``runtime/content``. This adapter atomically projects
one owned artifact per assignment into the native ``mods/`` or ``plugins/`` tree.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from urllib.parse import quote
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_SAFE_MOD_ID = re.compile(r"^[^;\r\n]{1,191}$")
_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]{1,12}$")

# Compatibility for RuntimeSpecs materialized before RuntimeDefinition.content.managed
# was propagated to the Agent. New specs carry the catalog-owned contract.
_LEGACY_MINECRAFT_TYPES: dict[str, dict[str, dict[str, Any]]] = {
    "minecraft.java.paper": {"plugin": {"directory": "plugins", "extensions": [".jar"]}},
    "minecraft.java.purpur": {"plugin": {"directory": "plugins", "extensions": [".jar"]}},
    "minecraft.java.folia": {"plugin": {"directory": "plugins", "extensions": [".jar"]}},
    "minecraft.java.fabric": {"mod": {"directory": "mods", "extensions": [".jar"]}},
    "minecraft.java.forge": {"mod": {"directory": "mods", "extensions": [".jar"]}},
    "minecraft.java.neoforge": {"mod": {"directory": "mods", "extensions": [".jar"]}},
    "minecraft.java.quilt": {"mod": {"directory": "mods", "extensions": [".jar"]}},
    # SpongeVanilla loads Sponge plugins from the mods directory.
    "minecraft.java.spongevanilla": {"plugin": {"directory": "mods", "extensions": [".jar"]}},
    "minecraft.java.arclight": {
        "mod": {"directory": "mods", "extensions": [".jar"]},
        "plugin": {"directory": "plugins", "extensions": [".jar"]},
    },
    "minecraft.java.youer": {
        "mod": {"directory": "mods", "extensions": [".jar"]},
        "plugin": {"directory": "plugins", "extensions": [".jar"]},
    },
}


class MinecraftContentActivationError(RuntimeError):
    pass


def _entries(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    values = snapshot.get("entries") if isinstance(snapshot, dict) else []
    if not isinstance(values, list):
        raise MinecraftContentActivationError("invalid activation snapshot")
    return [dict(value) for value in values if isinstance(value, dict)]


def _adapter(entry: dict[str, Any]) -> str:
    game = str(entry.get("game_id") or "").strip().lower()
    activation = entry.get("activation") if isinstance(entry.get("activation"), dict) else {}
    declared = str(activation.get("adapter") or "").strip().lower()
    canonical = {
        "dayz": "dayz",
        "projectzomboid": "project-zomboid",
        "minecraft": "minecraft-java",
    }.get(game, "")
    if declared and canonical and declared != canonical:
        raise MinecraftContentActivationError("content activation adapter does not match game")
    return canonical or declared


def _managed_path(entry: dict[str, Any]) -> str:
    value = str(entry.get("managed_path") or "").strip()
    if not value or not os.path.isabs(value) or any(char in value for char in ("\x00", "\r", "\n", ";")):
        raise MinecraftContentActivationError("invalid managed content path")
    return str(Path(value))

def _safe_artifact_filename(value: Any, extensions: list[str]) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > 240 or text in {".", ".."} or text.startswith("."):
        raise MinecraftContentActivationError("invalid Minecraft artifact filename")
    if any(char in text for char in ("\x00", "\r", "\n", "/", "\\")):
        raise MinecraftContentActivationError("invalid Minecraft artifact filename")
    path = Path(text)
    if path.name != text or path.suffix.lower() not in {str(v).lower() for v in extensions}:
        raise MinecraftContentActivationError("Minecraft artifact filename extension is not allowed")
    return text


def _safe_relative_directory(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = Path(text)
    if not text or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MinecraftContentActivationError("invalid managed content projection directory")
    if any(char in text for char in ("\x00", "\r", "\n", ";")):
        raise MinecraftContentActivationError("invalid managed content projection directory")
    return path.as_posix()


def _minecraft_managed_contract(spec: dict[str, Any]) -> bool:
    environment_id = str(spec.get("environment_id") or "").strip().lower()
    return "content_projection" in spec or environment_id in _LEGACY_MINECRAFT_TYPES


def _minecraft_policy(spec: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    if "content_projection" in spec:
        raw = spec.get("content_projection")
        if raw in (None, {}):
            return None
        if not isinstance(raw, dict) or str(raw.get("adapter") or "").strip().lower() != "minecraft-java":
            raise MinecraftContentActivationError("invalid Minecraft managed content adapter")
        types = raw.get("types")
        if not isinstance(types, dict) or not types or len(types) > 8:
            raise MinecraftContentActivationError("invalid Minecraft managed content types")
    else:
        environment_id = str(spec.get("environment_id") or "").strip().lower()
        types = _LEGACY_MINECRAFT_TYPES.get(environment_id)
        if types is None:
            return None

    normalized: dict[str, dict[str, Any]] = {}
    for raw_type, raw_config in types.items():
        content_type = str(raw_type or "").strip().lower()
        if content_type not in {"mod", "plugin", "datapack"} or not isinstance(raw_config, dict):
            raise MinecraftContentActivationError("unsupported Minecraft managed content type")
        directory = _safe_relative_directory(raw_config.get("directory"))
        extensions = raw_config.get("extensions")
        if not isinstance(extensions, list) or not extensions or len(extensions) > 8:
            raise MinecraftContentActivationError("invalid Minecraft managed content extensions")
        cleaned: list[str] = []
        for value in extensions:
            extension = str(value or "").strip().lower()
            if not _SAFE_EXTENSION.fullmatch(extension):
                raise MinecraftContentActivationError("invalid Minecraft managed content extension")
            if extension not in cleaned:
                cleaned.append(extension)
        normalized[content_type] = {"directory": directory, "extensions": cleaned}
    return normalized


def project_minecraft_files(spec: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    minecraft_entries = [entry for entry in entries if _adapter(entry) == "minecraft-java" and str((entry.get("activation") or {}).get("mode") or "").strip().lower() != "bundle-parent"]
    if not minecraft_entries:
        return []
    policy = _minecraft_policy(spec)
    if not policy:
        raise MinecraftContentActivationError("runtime does not support managed Minecraft content")
    projections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in minecraft_entries:
        content_id = str(entry.get("content_id") or "").strip()
        if (
            not content_id
            or len(content_id) > 191
            or any(char in content_id for char in ("\\x00", "\\r", "\\n", "/", "\\"))
        ):
            raise MinecraftContentActivationError("invalid Minecraft content identifier")
        projection_id = quote(content_id, safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
        if not projection_id or len(projection_id) > 240:
            raise MinecraftContentActivationError("Minecraft content identifier is too long for native projection")
        content_type = str(entry.get("content_type") or "").strip().lower()
        config = policy.get(content_type)
        if config is None:
            raise MinecraftContentActivationError(f"Minecraft runtime does not support content type: {content_type or 'unknown'}")
        extensions = list(config["extensions"])
        filename = _safe_artifact_filename(entry.get("artifact_filename"), extensions)
        projection = {
            "content_id": content_id,
            "content_type": content_type,
            "managed_path": _managed_path(entry),
            "extensions": extensions,
        }
        if filename is None:
            target = f"{config['directory'].rstrip('/')}/capivara-{projection_id}"
            if target in seen:
                raise MinecraftContentActivationError("duplicate Minecraft content projection")
            projection["target_stem"] = target
        else:
            target = f"{config['directory'].rstrip('/')}/{filename}"
            if target in seen:
                candidate = Path(filename)
                suffix = hashlib.sha256(content_id.encode("utf-8")).hexdigest()[:8]
                filename = f"{candidate.stem}-{suffix}{candidate.suffix}"
                target = f"{config['directory'].rstrip('/')}/{filename}"
            if target in seen:
                raise MinecraftContentActivationError("duplicate Minecraft content projection")
            projection["target_name"] = target
        seen.add(target)
        projections.append(projection)
    return projections


def _runtime_root(spec: dict[str, Any]) -> Path:
    raw = spec.get("working_directory") or spec.get("path")
    if not raw:
        raise MinecraftContentActivationError("content activation has no runtime root")
    root = Path(str(raw)).resolve()
    if root.is_symlink():
        raise MinecraftContentActivationError("runtime root cannot be a symbolic link")
    return root


def _payload_file(runtime_root: Path, item: dict[str, Any]) -> Path:
    managed = Path(str(item.get("managed_path") or ""))
    if not managed.is_absolute() or managed.is_symlink():
        raise MinecraftContentActivationError("invalid Minecraft managed content source")
    try:
        source = managed.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MinecraftContentActivationError("Minecraft managed content source is missing") from exc
    content_root = (runtime_root / "content").resolve()
    try:
        source.relative_to(content_root)
    except ValueError as exc:
        raise MinecraftContentActivationError("Minecraft managed content source escapes content root") from exc
    extensions = {str(value).lower() for value in item.get("extensions") or []}
    if not extensions or any(not _SAFE_EXTENSION.fullmatch(value) for value in extensions):
        raise MinecraftContentActivationError("invalid Minecraft projection extensions")
    candidates: list[Path] = []
    if source.is_file():
        if source.suffix.lower() in extensions:
            candidates.append(source)
    elif source.is_dir():
        for current, dirs, files in os.walk(source, followlinks=False):
            current_path = Path(current)
            for name in list(dirs):
                if (current_path / name).is_symlink():
                    raise MinecraftContentActivationError("Minecraft managed content contains a symbolic link")
            for name in files:
                candidate = current_path / name
                if candidate.is_symlink():
                    raise MinecraftContentActivationError("Minecraft managed content contains a symbolic link")
                if candidate.is_file() and candidate.suffix.lower() in extensions:
                    candidates.append(candidate.resolve())
    if len(candidates) != 1:
        raise MinecraftContentActivationError("Minecraft mod/plugin assignment must contain exactly one supported artifact")
    return candidates[0]


def _managed_relative_target(value: str, extension: str | None = None) -> Path:
    text = str(value or "").strip().replace("\\", "/")
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2:
        raise MinecraftContentActivationError("invalid Minecraft native projection target")
    if relative.parts[0] not in {"mods", "plugins"}:
        raise MinecraftContentActivationError("unowned Minecraft native projection target")
    name = relative.name
    if name in {"", ".", ".."} or name.startswith(".") or any(char in name for char in ("\x00", "\r", "\n")):
        raise MinecraftContentActivationError("invalid Minecraft native projection filename")
    if extension is not None and not relative.name.endswith(extension):
        raise MinecraftContentActivationError("Minecraft projection target extension mismatch")
    return relative


def _manifest_path(spec: dict[str, Any]) -> Path:
    state_raw = spec.get("instance_state_root")
    if not state_raw:
        raise MinecraftContentActivationError("Minecraft activation requires instance_state_root")
    state = Path(str(state_raw)).resolve()
    return state / ".dsm" / "content-activation-files.json"


def _read_manifest(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise MinecraftContentActivationError("invalid Minecraft activation manifest") from exc
    if not isinstance(payload, dict) or payload.get("kind") != "CapivaraContentFileProjection":
        raise MinecraftContentActivationError("invalid Minecraft activation manifest")
    targets = payload.get("targets")
    if not isinstance(targets, list) or len(targets) > 512:
        raise MinecraftContentActivationError("invalid Minecraft activation manifest targets")
    result: list[str] = []
    for value in targets:
        relative = _managed_relative_target(str(value)).as_posix()
        if relative not in result:
            result.append(relative)
    return result


def _write_manifest(path: Path, targets: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "kind": "CapivaraContentFileProjection", "targets": sorted(targets)}
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, path)


def _safe_runtime_target(root: Path, relative: Path) -> Path:
    target = root / relative
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise MinecraftContentActivationError("Minecraft projection target escapes runtime") from exc
    if target.is_symlink():
        raise MinecraftContentActivationError("Minecraft projection target cannot be a symbolic link")
    return target


def materialize_minecraft_files(spec: dict[str, Any]) -> list[str]:
    if not _minecraft_managed_contract(spec):
        return []
    raw = spec.get("content_file_projections")
    items = raw if isinstance(raw, list) else []
    game = str(spec.get("game_id") or "").strip().lower()
    environment = str(spec.get("environment_id") or "").strip().lower()
    if game != "minecraft" and not environment.startswith("minecraft.") and not items and "content_projection" not in spec:
        return []
    if len(items) > 512:
        raise MinecraftContentActivationError("too many Minecraft content projections")
    root = _runtime_root(spec)
    manifest = _manifest_path(spec)
    previous = _read_manifest(manifest)
    previous_set = set(previous)
    desired: dict[str, Path] = {}
    for item in items:
        if not isinstance(item, dict):
            raise MinecraftContentActivationError("invalid Minecraft content projection")
        content_id = str(item.get("content_id") or "").strip()
        if (
            not content_id
            or len(content_id) > 191
            or any(char in content_id for char in ("\\x00", "\\r", "\\n", "/", "\\"))
        ):
            raise MinecraftContentActivationError("invalid Minecraft content projection identifier")
        source = _payload_file(root, item)
        extension = source.suffix.lower()
        target_name = str(item.get("target_name") or "").strip()
        if target_name:
            relative = _managed_relative_target(target_name, extension)
        else:
            stem = str(item.get("target_stem") or "")
            relative = _managed_relative_target(stem + extension, extension)
        key = relative.as_posix()
        if key in desired:
            raise MinecraftContentActivationError("duplicate Minecraft native projection target")
        desired[key] = source

    staged: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    placed: set[str] = set()
    try:
        # Stage every new artifact before mutating the native runtime directories.
        for relative_text, source in desired.items():
            relative = Path(relative_text)
            target = _safe_runtime_target(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and relative_text not in previous_set:
                raise MinecraftContentActivationError("refusing to overwrite unmanaged Minecraft runtime content")
            stage = target.with_name(f".{target.name}.{os.getpid()}.capivara-new")
            if stage.exists():
                if stage.is_dir():
                    shutil.rmtree(stage)
                else:
                    stage.unlink()
            shutil.copy2(source, stage)
            staged[relative_text] = stage

        # Replace desired managed targets while retaining reversible backups.
        for relative_text, stage in staged.items():
            target = _safe_runtime_target(root, Path(relative_text))
            if target.exists():
                if not target.is_file():
                    raise MinecraftContentActivationError("managed Minecraft target is not a regular file")
                backup = target.with_name(f".{target.name}.{os.getpid()}.capivara-old")
                os.replace(target, backup)
                backups[relative_text] = backup
            os.replace(stage, target)
            placed.add(relative_text)

        # Stale targets were created by Capivara according to the previous manifest.
        for relative_text in sorted(previous_set - set(desired)):
            target = _safe_runtime_target(root, _managed_relative_target(relative_text))
            if target.exists():
                if not target.is_file():
                    raise MinecraftContentActivationError("stale Minecraft managed target is not a regular file")
                backup = target.with_name(f".{target.name}.{os.getpid()}.capivara-old")
                os.replace(target, backup)
                backups[relative_text] = backup

        _write_manifest(manifest, list(desired))
    except Exception:
        for relative_text in placed:
            target = _safe_runtime_target(root, Path(relative_text))
            try:
                if target.exists() and target.is_file():
                    target.unlink()
            except OSError:
                pass
        for relative_text, backup in backups.items():
            target = _safe_runtime_target(root, _managed_relative_target(relative_text))
            try:
                if backup.exists():
                    if target.exists() and target.is_file():
                        target.unlink()
                    os.replace(backup, target)
            except OSError:
                pass
        for stage in staged.values():
            try:
                if stage.exists():
                    stage.unlink()
            except OSError:
                pass
        raise

    # The new manifest is committed. Backups are now disposable and cleanup is best effort.
    for backup in backups.values():
        try:
            if backup.exists():
                backup.unlink()
        except OSError:
            pass
    return sorted(desired)



def project_minecraft_bundle_overrides(spec: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parents = [entry for entry in entries if _adapter(entry) == "minecraft-java" and str((entry.get("activation") or {}).get("mode") or "").strip().lower() == "bundle-parent"]
    if not parents:
        return []
    if len(parents) != 1:
        raise MinecraftContentActivationError("Minecraft runtime supports exactly one active modpack bundle")
    entry = parents[0]
    activation = entry.get("activation") if isinstance(entry.get("activation"), dict) else {}
    raw_roots = str(activation.get("identifier") or "").strip()
    roots: list[str] = []
    for value in raw_roots.split(",") if raw_roots else []:
        root = value.strip()
        if not _SAFE_ID.fullmatch(root) or root in {".", ".."}:
            raise MinecraftContentActivationError("invalid Minecraft modpack override root")
        if root not in roots:
            roots.append(root)
    if len(roots) > 8:
        raise MinecraftContentActivationError("too many Minecraft modpack override roots")
    return [{"content_id": str(entry.get("content_id") or ""), "managed_path": _managed_path(entry), "roots": roots}]


def _override_manifest_path(spec: dict[str, Any]) -> Path:
    state_raw = spec.get("instance_state_root")
    if not state_raw:
        raise MinecraftContentActivationError("Minecraft overrides require instance_state_root")
    return Path(str(state_raw)).resolve() / ".dsm" / "content-activation-overrides.json"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_override_manifest(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise MinecraftContentActivationError("invalid Minecraft override manifest") from exc
    if not isinstance(payload, dict) or payload.get("kind") != "CapivaraContentOverrideProjection":
        raise MinecraftContentActivationError("invalid Minecraft override manifest")
    targets = payload.get("targets")
    if not isinstance(targets, list) or len(targets) > 20000:
        raise MinecraftContentActivationError("invalid Minecraft override targets")
    result: dict[str, str] = {}
    for item in targets:
        if not isinstance(item, dict):
            raise MinecraftContentActivationError("invalid Minecraft override target")
        relative = _safe_override_target(item.get("path")).as_posix()
        checksum = str(item.get("sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise MinecraftContentActivationError("invalid Minecraft override checksum")
        result[relative] = checksum
    return result


def _write_override_manifest(path: Path, targets: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "kind": "CapivaraContentOverrideProjection", "targets": [{"path": key, "sha256": targets[key]} for key in sorted(targets)]}
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, path)


def _safe_override_target(value: Any) -> Path:
    text = str(value or "").strip().replace("\\", "/")
    path = Path(text)
    if not text or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MinecraftContentActivationError("invalid Minecraft override target")
    first = path.parts[0].lower()
    if first in {"mods", "plugins", ".dsm", "libraries", "versions", "runtime", "content", "logs"}:
        raise MinecraftContentActivationError("Minecraft modpack override targets a protected runtime path")
    if path.suffix.lower() in {".jar", ".exe", ".dll", ".so", ".dylib", ".bat", ".cmd", ".ps1", ".sh"}:
        raise MinecraftContentActivationError("Minecraft modpack override contains a protected executable artifact")
    return path


def _bundle_source(runtime_root: Path, item: dict[str, Any]) -> Path:
    managed = Path(str(item.get("managed_path") or ""))
    if not managed.is_absolute() or managed.is_symlink():
        raise MinecraftContentActivationError("invalid Minecraft modpack managed source")
    try:
        source = managed.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MinecraftContentActivationError("Minecraft modpack managed source is missing") from exc
    content_root = (runtime_root / "content").resolve()
    try:
        source.relative_to(content_root)
    except ValueError as exc:
        raise MinecraftContentActivationError("Minecraft modpack source escapes content root") from exc
    if not source.is_dir():
        raise MinecraftContentActivationError("Minecraft modpack source is not an extracted directory")
    return source


def materialize_minecraft_overrides(spec: dict[str, Any]) -> list[str]:
    if not _minecraft_managed_contract(spec):
        return []
    raw = spec.get("content_bundle_overrides")
    items = raw if isinstance(raw, list) else []
    if len(items) > 1:
        raise MinecraftContentActivationError("Minecraft runtime supports exactly one active modpack bundle")
    # Legacy/non-bundle RuntimeSpecs may not carry instance_state_root. With no
    # active bundle there is nothing to apply or clean, so keep this a no-op.
    # Once a bundle exists, instance_state_root is mandatory so ownership can be
    # persisted and later disable/remove can safely clean managed overrides.
    if not items and not spec.get("instance_state_root"):
        return []
    root = _runtime_root(spec)
    roots: list[str] = []
    source: Path | None = None
    if items:
        source = _bundle_source(root, items[0])
        roots = items[0].get("roots") if isinstance(items[0].get("roots"), list) else []
    desired_sources: dict[str, Path] = {}
    desired_hashes: dict[str, str] = {}
    count = 0
    total = 0
    for raw_root in roots:
        root_name = str(raw_root or "").strip()
        if not _SAFE_ID.fullmatch(root_name):
            raise MinecraftContentActivationError("invalid Minecraft modpack override root")
        if source is None:
            raise MinecraftContentActivationError("Minecraft modpack override source is unavailable")
        layer = source / root_name
        if not layer.is_dir() or layer.is_symlink():
            raise MinecraftContentActivationError("Minecraft modpack override root is missing")
        for current, dirs, files in os.walk(layer, followlinks=False):
            current_path = Path(current)
            for name in list(dirs):
                if (current_path / name).is_symlink():
                    raise MinecraftContentActivationError("Minecraft modpack override contains a symbolic link")
            for name in files:
                candidate = current_path / name
                if candidate.is_symlink() or not candidate.is_file():
                    raise MinecraftContentActivationError("Minecraft modpack override contains an unsafe file")
                relative = _safe_override_target(candidate.relative_to(layer).as_posix()).as_posix()
                count += 1
                total += candidate.stat().st_size
                if count > 20000 or total > 4 * 1024 * 1024 * 1024:
                    raise MinecraftContentActivationError("Minecraft modpack overrides exceed safety limits")
                desired_sources[relative] = candidate.resolve()
                desired_hashes[relative] = _file_sha256(candidate)
    manifest = _override_manifest_path(spec)
    previous = _read_override_manifest(manifest)
    staged: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    placed: set[str] = set()
    try:
        for relative_text, source_file in desired_sources.items():
            target = _safe_runtime_target(root, _safe_override_target(relative_text))
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if relative_text not in previous:
                    raise MinecraftContentActivationError("refusing to overwrite unmanaged Minecraft modpack file")
                if not target.is_file() or target.is_symlink() or _file_sha256(target) != previous[relative_text]:
                    raise MinecraftContentActivationError("managed Minecraft modpack file was modified locally")
            stage = target.with_name(f".{target.name}.{os.getpid()}.capivara-bundle-new")
            if stage.exists():
                stage.unlink()
            shutil.copy2(source_file, stage)
            staged[relative_text] = stage
        for relative_text, stage in staged.items():
            target = _safe_runtime_target(root, _safe_override_target(relative_text))
            if target.exists():
                backup = target.with_name(f".{target.name}.{os.getpid()}.capivara-bundle-old")
                os.replace(target, backup)
                backups[relative_text] = backup
            os.replace(stage, target)
            placed.add(relative_text)
        for relative_text, checksum in sorted(previous.items()):
            if relative_text in desired_sources:
                continue
            target = _safe_runtime_target(root, _safe_override_target(relative_text))
            if target.exists():
                if not target.is_file() or target.is_symlink() or _file_sha256(target) != checksum:
                    raise MinecraftContentActivationError("stale Minecraft modpack file was modified locally")
                backup = target.with_name(f".{target.name}.{os.getpid()}.capivara-bundle-old")
                os.replace(target, backup)
                backups[relative_text] = backup
        _write_override_manifest(manifest, desired_hashes)
    except Exception:
        for relative_text in placed:
            target = _safe_runtime_target(root, _safe_override_target(relative_text))
            try:
                if target.exists() and target.is_file():
                    target.unlink()
            except OSError:
                pass
        for relative_text, backup in backups.items():
            target = _safe_runtime_target(root, _safe_override_target(relative_text))
            try:
                if backup.exists():
                    if target.exists() and target.is_file():
                        target.unlink()
                    os.replace(backup, target)
            except OSError:
                pass
        for stage in staged.values():
            try:
                if stage.exists():
                    stage.unlink()
            except OSError:
                pass
        raise
    for backup in backups.values():
        try:
            if backup.exists():
                backup.unlink()
        except OSError:
            pass
    return sorted(desired_sources)


__all__=["MinecraftContentActivationError","materialize_minecraft_files","materialize_minecraft_overrides","project_minecraft_bundle_overrides","project_minecraft_files"]
