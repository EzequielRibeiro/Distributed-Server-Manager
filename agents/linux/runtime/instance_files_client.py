#!/usr/bin/env python3
"""Agent-owned safe file manager for one game-server instance.

All paths are resolved below the instance's customer-manageable files root.
Symlinks, traversal, protected runtime paths and content-policy bypasses are
rejected on the Agent even when a request came from an authenticated Controller.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
from typing import Any
import zipfile

import instance_runtime

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
RESULT_DIR = STATE_DIR / "file-results"
HISTORY_DIR = STATE_DIR / "file-history"
MAX_TRANSFER_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10000
EDITABLE_SUFFIXES = {".txt", ".cfg", ".conf", ".config", ".ini", ".json", ".properties", ".toml", ".xml", ".yaml", ".yml", ".log", ".md", ".csv"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_id(value: Any, label: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 191 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in value):
        raise ValueError(f"invalid {label}")
    return value


def _state_path(root: Path, command_id: str) -> Path:
    return root / f"{_safe_id(command_id, 'command_id')}.json"


def _read(path: Path):
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return None
    return value if isinstance(value, dict) else None


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _owned(config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    record = instance_runtime.get_instance(_safe_id(instance_id, "instance_id"))
    if not isinstance(record, dict):
        raise LookupError("instance not found")
    if str(record.get("agent_id") or "") != str(config.get("agent_id") or ""):
        raise PermissionError("instance belongs to another Agent")
    return record


def _files_root(record: dict[str, Any]) -> Path:
    raw = record.get("files_root") or record.get("configuration_root") or record.get("working_directory") or record.get("path")
    root = Path(str(raw or ""))
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise RuntimeError("instance customer files root is unavailable")
    return root.resolve()


def _relative(value: Any) -> Path:
    raw = str(value or ".").replace("\\", "/")
    value = Path(raw)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError("invalid instance file path")
    return Path(*[part for part in value.parts if part not in {"", "."}])


def _resolve(root: Path, value: Any, *, missing: bool = False) -> Path:
    relative = _relative(value)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symbolic links are not allowed")
    candidate = (root / relative).resolve(strict=False)
    candidate.relative_to(root)
    if not missing and not candidate.exists():
        raise FileNotFoundError(relative.as_posix())
    return candidate


def _policy(command: dict[str, Any]) -> dict[str, Any]:
    value = command.get("policy")
    return value if isinstance(value, dict) else {}


def _parts_set(raw: Any) -> set[str]:
    if not isinstance(raw, list): return set()
    return {str(item).strip().strip("/\\").lower() for item in raw if str(item).strip()}


def _path_under(relative: Path, roots: set[str]) -> bool:
    text = relative.as_posix().lower()
    return any(text == root or text.startswith(root.rstrip("/") + "/") for root in roots)


def _guard_path_policy(relative: Path, policy: dict[str, Any], *, upload: bool = False) -> None:
    file_policy = policy.get("file_policy") if isinstance(policy.get("file_policy"), dict) else {}
    content = policy.get("content_policy") if isinstance(policy.get("content_policy"), dict) else {}
    protected = _parts_set(file_policy.get("protected_paths")) | {".dsm", "runtime"}
    if relative.parts and str(relative.parts[0]).lower() in protected:
        raise PermissionError("protected instance path")
    if not upload:
        return
    if not bool(content.get("external_upload_allowed", True)):
        raise PermissionError("external uploads are not allowed by this contract")
    mod_paths = _parts_set(file_policy.get("mod_paths"))
    plugin_paths = _parts_set(file_policy.get("plugin_paths"))
    workshop_paths = _parts_set(file_policy.get("workshop_paths"))
    if _path_under(relative, mod_paths) and not bool(content.get("mods_allowed")):
        raise PermissionError("mods are not allowed by this contract")
    if _path_under(relative, plugin_paths) and not bool(content.get("plugins_allowed")):
        raise PermissionError("plugins are not allowed by this contract")
    if _path_under(relative, workshop_paths) and not bool(content.get("workshop_allowed")):
        raise PermissionError("Workshop content is not allowed by this contract")
    runtime_extensions = {str(x).lower() for x in (file_policy.get("runtime_extensions") or [])}
    in_content_path = _path_under(relative, mod_paths | plugin_paths | workshop_paths)
    if relative.suffix.lower() in runtime_extensions and not in_content_path and not bool(content.get("custom_runtime_allowed")):
        raise PermissionError("custom runtime artifacts are not allowed by this contract")


def _usage(root: Path) -> int:
    total = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        base_path = Path(base)
        dirs[:] = [name for name in dirs if not (base_path / name).is_symlink()]
        for name in files:
            path = base_path / name
            if path.is_symlink(): continue
            try: total += path.stat().st_size
            except OSError: pass
    return total


def _quota(policy: dict[str, Any]) -> int | None:
    value = policy.get("storage_limit_bytes")
    try: result = int(value) if value is not None else None
    except (TypeError, ValueError): result = None
    return result if result and result > 0 else None


def _ensure_quota(root: Path, policy: dict[str, Any], added: int, *, replacing: Path | None = None) -> None:
    limit = _quota(policy)
    if limit is None: return
    current = _usage(root)
    previous = 0
    if replacing is not None and replacing.is_file() and not replacing.is_symlink():
        previous = replacing.stat().st_size
    projected = current - previous + max(0, int(added))
    if projected > limit:
        raise OSError(f"storage quota exceeded: {projected} > {limit}")


def _entry(root: Path, path: Path) -> dict[str, Any]:
    stat = path.stat()
    rel = path.relative_to(root).as_posix()
    return {
        "name": path.name,
        "path": rel,
        "directory": path.is_dir(),
        "size": None if path.is_dir() else stat.st_size,
        "modified_at": int(stat.st_mtime),
        "editable": path.is_file() and path.suffix.lower() in EDITABLE_SUFFIXES and stat.st_size <= 2 * 1024 * 1024,
    }


def _list(root: Path, path_value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    directory = _resolve(root, path_value)
    if not directory.is_dir(): raise ValueError("path is not a directory")
    entries = []
    for child in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.is_symlink(): continue
        rel = child.relative_to(root)
        try: _guard_path_policy(rel, policy)
        except PermissionError: continue
        entries.append(_entry(root, child))
    return {"path": directory.relative_to(root).as_posix() or ".", "entries": entries, "usage_bytes": _usage(root), "limit_bytes": _quota(policy)}


def _read_text(root: Path, path_value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, path_value); rel = path.relative_to(root); _guard_path_policy(rel, policy)
    if not path.is_file() or path.suffix.lower() not in EDITABLE_SUFFIXES: raise ValueError("file is not editable text")
    if path.stat().st_size > 2 * 1024 * 1024: raise ValueError("editable file is too large")
    return {"path": rel.as_posix(), "content": path.read_text(encoding="utf-8"), "size": path.stat().st_size}


def _write_text(root: Path, path_value: Any, payload: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, path_value, missing=True); rel = path.relative_to(root); _guard_path_policy(rel, policy, upload=True)
    content = payload.get("content")
    if not isinstance(content, str): raise ValueError("content must be text")
    encoded = content.encode("utf-8")
    if len(encoded) > 2 * 1024 * 1024: raise ValueError("editable file is too large")
    if path.suffix.lower() not in EDITABLE_SUFFIXES: raise ValueError("file type is not editable")
    if not path.parent.is_dir(): raise ValueError("destination directory does not exist")
    _ensure_quota(root, policy, len(encoded), replacing=path)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp"); temp.write_bytes(encoded); os.replace(temp, path)
    return {"path": rel.as_posix(), "size": len(encoded), "saved": True}


def _decode_upload(payload: dict[str, Any]) -> bytes:
    raw = payload.get("content_base64")
    if not isinstance(raw, str): raise ValueError("content_base64 is required")
    try: data = base64.b64decode(raw, validate=True)
    except Exception as exc: raise ValueError("invalid base64 upload") from exc
    if len(data) > MAX_TRANSFER_BYTES: raise ValueError("uploaded file exceeds transfer limit")
    return data


def _upload(root: Path, path_value: Any, payload: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, path_value, missing=True); rel = path.relative_to(root); _guard_path_policy(rel, policy, upload=True)
    if not path.parent.is_dir(): raise ValueError("destination directory does not exist")
    data = _decode_upload(payload); _ensure_quota(root, policy, len(data), replacing=path)
    temp = path.with_name(f".{path.name}.{os.getpid()}.upload"); temp.write_bytes(data); os.replace(temp, path)
    return {"path": rel.as_posix(), "size": len(data), "uploaded": True}


def _download(root: Path, path_value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, path_value); rel = path.relative_to(root); _guard_path_policy(rel, policy)
    if not path.is_file(): raise ValueError("path is not a file")
    data = path.read_bytes()
    if len(data) > MAX_TRANSFER_BYTES: raise ValueError("file exceeds transfer limit")
    return {"path": rel.as_posix(), "name": path.name, "size": len(data), "content_base64": base64.b64encode(data).decode("ascii")}


def _mkdir(root: Path, path_value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, path_value, missing=True); rel = path.relative_to(root); _guard_path_policy(rel, policy, upload=True)
    if path.exists(): raise FileExistsError(rel.as_posix())
    if not path.parent.is_dir(): raise ValueError("parent directory does not exist")
    path.mkdir(mode=0o750)
    return {"path": rel.as_posix(), "created": True}


def _delete(root: Path, path_value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, path_value); rel = path.relative_to(root); _guard_path_policy(rel, policy)
    if path == root: raise PermissionError("instance files root cannot be deleted")
    if path.is_dir(): shutil.rmtree(path)
    else: path.unlink()
    return {"path": rel.as_posix(), "deleted": True}


def _move(root: Path, source_value: Any, target_value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    source = _resolve(root, source_value); target = _resolve(root, target_value, missing=True)
    source_rel = source.relative_to(root); target_rel = target.relative_to(root)
    _guard_path_policy(source_rel, policy); _guard_path_policy(target_rel, policy, upload=True)
    if source == root or target == root: raise PermissionError("invalid move target")
    if target.exists(): raise FileExistsError(target_rel.as_posix())
    if not target.parent.is_dir(): raise ValueError("target parent does not exist")
    shutil.move(str(source), str(target))
    return {"from": source_rel.as_posix(), "to": target_rel.as_posix(), "moved": True}


def _archive_members(data: bytes, name: str):
    lower = name.lower()
    if lower.endswith(".zip"):
        archive = zipfile.ZipFile(io.BytesIO(data), "r")
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS: archive.close(); raise ValueError("archive has too many entries")
        def members():
            for info in infos:
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000: raise ValueError("archive symbolic links are not allowed")
                yield info.filename, info.file_size, info.is_dir(), lambda i=info: archive.open(i, "r")
        return archive, members()
    if lower.endswith((".tar", ".tar.gz", ".tgz")):
        mode = "r:gz" if lower.endswith((".tar.gz", ".tgz")) else "r:"
        archive = tarfile.open(fileobj=io.BytesIO(data), mode=mode)
        infos = archive.getmembers()
        if len(infos) > MAX_ARCHIVE_MEMBERS: archive.close(); raise ValueError("archive has too many entries")
        def members():
            for info in infos:
                if info.issym() or info.islnk() or info.isdev(): raise ValueError("archive links/devices are not allowed")
                yield info.name, info.size, info.isdir(), lambda i=info: archive.extractfile(i)
        return archive, members()
    raise ValueError("unsupported archive type")


def _extract(root: Path, archive_value: Any, target_value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    archive_path = _resolve(root, archive_value); archive_rel = archive_path.relative_to(root); _guard_path_policy(archive_rel, policy)
    target = _resolve(root, target_value or archive_path.parent.relative_to(root), missing=True)
    if not target.exists(): target.mkdir(parents=False)
    if not target.is_dir(): raise ValueError("extract target is not a directory")
    data = archive_path.read_bytes()
    if len(data) > MAX_TRANSFER_BYTES: raise ValueError("archive exceeds transfer limit")
    archive, members = _archive_members(data, archive_path.name)
    planned = []
    total = 0
    try:
        for raw_name, size, directory, opener in members:
            rel_member = _relative(raw_name)
            destination = (target / rel_member).resolve(strict=False); destination.relative_to(root)
            rel = destination.relative_to(root); _guard_path_policy(rel, policy, upload=True)
            total += max(0, int(size or 0))
            planned.append((destination, directory, opener))
        _ensure_quota(root, policy, total)
        for destination, directory, opener in planned:
            if directory:
                destination.mkdir(parents=True, exist_ok=True); continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            handle = opener()
            if handle is None: continue
            with handle, destination.open("wb") as out: shutil.copyfileobj(handle, out, length=1024 * 1024)
    finally:
        archive.close()
    return {"archive": archive_rel.as_posix(), "target": target.relative_to(root).as_posix(), "entries": len(planned), "expanded_bytes": total, "extracted": True}


def execute(config: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    record = _owned(config, str(command.get("instance_id") or "")); root = _files_root(record); policy = _policy(command)
    action = str(command.get("action") or "").strip().lower(); path = command.get("path"); target = command.get("target_path"); payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    if action == "list": return _list(root, path, policy)
    if action == "usage": return {"usage_bytes": _usage(root), "limit_bytes": _quota(policy)}
    if action == "read_text": return _read_text(root, path, policy)
    if action == "write_text": return _write_text(root, path, payload, policy)
    if action == "download": return _download(root, path, policy)
    if action == "upload": return _upload(root, path, payload, policy)
    if action == "mkdir": return _mkdir(root, path, policy)
    if action == "delete": return _delete(root, path, policy)
    if action in {"rename", "move"}: return _move(root, path, target, policy)
    if action == "extract": return _extract(root, path, target, policy)
    raise ValueError("unsupported instance file action")


def handle_command(config: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    command_id = _safe_id(command.get("command_id"), "command_id"); history = _state_path(HISTORY_DIR, command_id)
    previous = _read(history)
    if previous is not None: _write(_state_path(RESULT_DIR, command_id), previous); return previous
    instance_id = str(command.get("instance_id") or ""); action = str(command.get("action") or "")
    try:
        result = execute(config, command)
        report = {"command_id": command_id, "instance_id": instance_id, "action": action, "status": "completed", "result": result, "generated_at": _now()}
    except Exception as exc:
        report = {"command_id": command_id, "instance_id": instance_id or None, "action": action or None, "status": "failed", "error": str(exc)[:4000], "generated_at": _now()}
    _write(history, report); _write(_state_path(RESULT_DIR, command_id), report); return report


def read_result() -> dict[str, Any] | None:
    try: paths = sorted(RESULT_DIR.glob("*.json"))
    except OSError: paths = []
    for path in paths:
        value = _read(path)
        if value: return value
    return None


def clear_result(command_id: str) -> None:
    try: _state_path(RESULT_DIR, command_id).unlink()
    except FileNotFoundError: pass


__all__ = ["clear_result", "execute", "handle_command", "read_result"]
