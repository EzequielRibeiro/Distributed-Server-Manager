#!/usr/bin/env python3
"""Resolve trusted catalog RuntimeDefinition objects into Agent launch profiles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_EXECUTABLE = re.compile(r"^[A-Za-z0-9._+-]{1,128}$")
SUPPORTED_ENGINES = {"native", "java"}


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise ValueError(f"invalid {label}")
    return text


def _normalize_args(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value] if value else []
    elif isinstance(value, list):
        values = [str(item) for item in value]
    else:
        raise ValueError("runtime process args must be a string or list")
    if len(values) > 64:
        raise ValueError("runtime process has too many arguments")
    for item in values:
        if len(item) > 512 or any(char in item for char in ("\x00", "\n", "\r")):
            raise ValueError("runtime process contains an invalid argument")
    return values


def resolve_launch_profile(root: Path, runtime_id: str, *, expected_game_id: str | None = None) -> dict[str, Any]:
    runtime_id = _token(runtime_id, "runtime_id")
    catalog_root = Path(root) / "catalog" / "v2" / "runtimes"
    selected: dict[str, Any] | None = None
    for path in sorted(catalog_root.glob("*/*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and str(value.get("id") or "") == runtime_id:
            selected = value
            break
    if selected is None:
        raise ValueError("runtime_id not found in catalog")
    if selected.get("kind") != "RuntimeDefinition":
        raise ValueError("catalog runtime has invalid kind")
    game_id = _token(selected.get("game"), "game_id")
    if expected_game_id and game_id != str(expected_game_id):
        raise ValueError("runtime game does not match instance")
    process = selected.get("process")
    if not isinstance(process, dict):
        raise ValueError("catalog runtime has no process definition")
    engine = str(process.get("engine") or "").strip().lower()
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"runtime engine is not supported by Agent service provisioning: {engine or 'missing'}")
    executable = str(process.get("executable") or "").strip()
    if not _EXECUTABLE.fullmatch(executable):
        raise ValueError("runtime executable must be a safe artifact basename")
    return {
        "runtime_id": runtime_id,
        "environment_id": runtime_id,
        "game_id": game_id,
        "adapter": "systemd",
        "engine": engine,
        "executable": executable,
        "args": _normalize_args(process.get("args")),
    }


__all__ = ["SUPPORTED_ENGINES", "resolve_launch_profile"]
