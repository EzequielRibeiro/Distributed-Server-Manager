#!/usr/bin/env python3
"""Safe file operations confined to one resolved Agent game-data root."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
from typing import Any

MAX_TEXT_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def _relative(value: Any, *, allow_root: bool = True) -> Path:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        if allow_root:
            return Path(".")
        raise ValueError("path is required")
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("path must be relative to game-data root")
    return candidate


def _resolve(root: Path, value: Any, *, allow_root: bool = True, must_exist: bool = False) -> Path:
    root = root.resolve()
    relative = _relative(value, allow_root=allow_root)
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes game-data root") from exc
    if candidate != root:
        cursor = root
        for part in relative.parts:
            if part in {"", "."}:
                continue
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                resolved = cursor.resolve()
                try:
                    resolved.relative_to(root)
                except ValueError as exc:
                    raise ValueError("symlink escapes game-data root") from exc
    if must_exist and not candidate.exists():
        raise FileNotFoundError(str(relative))
    return candidate


def _entry(root: Path, path: Path) -> dict[str, Any]:
    stat = path.lstat()
    relative = path.relative_to(root).as_posix()
    if relative == ".":
        relative = ""
    return {
        "name": path.name or root.name,
        "path": relative,
        "type": "directory" if path.is_dir() else "file",
        "size": stat.st_size if path.is_file() else None,
        "modified_ns": stat.st_mtime_ns,
        "writable": os.access(path, os.W_OK),
    }


def execute_file_operation(root: Path, operation: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise RuntimeError("game-data is not installed")
    action = str(operation.get("action") or "").strip().lower()
    path = operation.get("path")

    if action == "list":
        directory = _resolve(root, path, must_exist=True)
        if not directory.is_dir():
            raise ValueError("path is not a directory")
        entries = [_entry(root, item) for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))]
        return {"operation": action, "path": directory.relative_to(root).as_posix().replace(".", "", 1), "entries": entries[:2000]}

    if action == "read":
        target = _resolve(root, path, allow_root=False, must_exist=True)
        if not target.is_file():
            raise ValueError("path is not a file")
        if target.stat().st_size > MAX_TEXT_BYTES:
            raise ValueError("file exceeds editable text limit")
        raw = target.read_bytes()
        if b"\x00" in raw:
            raise ValueError("binary files cannot be edited as text")
        return {"operation": action, "path": target.relative_to(root).as_posix(), "content": raw.decode("utf-8"), "size": len(raw)}

    if action in {"write", "create"}:
        target = _resolve(root, path, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        if action == "create" and target.exists():
            raise FileExistsError(str(path))
        content = str(operation.get("content") or "")
        raw = content.encode("utf-8")
        if len(raw) > MAX_TEXT_BYTES:
            raise ValueError("content exceeds editable text limit")
        temp = target.with_name(target.name + ".capivara-tmp")
        temp.write_bytes(raw)
        temp.replace(target)
        return {"operation": action, "path": target.relative_to(root).as_posix(), "size": len(raw), "modified": True}

    if action == "mkdir":
        target = _resolve(root, path, allow_root=False)
        target.mkdir(parents=True, exist_ok=False)
        return {"operation": action, "path": target.relative_to(root).as_posix(), "modified": True}

    if action == "rename":
        source = _resolve(root, path, allow_root=False, must_exist=True)
        destination = _resolve(root, operation.get("destination"), allow_root=False)
        if destination.exists():
            raise FileExistsError(str(operation.get("destination") or ""))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        return {"operation": action, "path": source.relative_to(root).as_posix(), "destination": destination.relative_to(root).as_posix(), "modified": True}

    if action == "delete":
        target = _resolve(root, path, allow_root=False, must_exist=True)
        relative = target.relative_to(root).as_posix()
        if target.is_dir():
            if any(target.iterdir()) and not bool(operation.get("recursive")):
                raise ValueError("directory is not empty")
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"operation": action, "path": relative, "modified": True}

    if action == "upload":
        target = _resolve(root, path, allow_root=False)
        encoded = str(operation.get("content_base64") or "")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("invalid base64 upload") from exc
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError("upload exceeds size limit")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".capivara-upload")
        temp.write_bytes(raw)
        temp.replace(target)
        return {"operation": action, "path": target.relative_to(root).as_posix(), "size": len(raw), "modified": True}

    raise ValueError("unsupported game-data file operation")


__all__ = ["MAX_TEXT_BYTES", "MAX_UPLOAD_BYTES", "execute_file_operation"]
