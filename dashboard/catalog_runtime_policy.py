#!/usr/bin/env python3
"""Persistent, validated runtime/startup policy for Catalog runtimes."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_RUNTIME_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_VAR_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_TEMPLATE_BYTES = 1024 * 1024


def _state_root(root: Path) -> Path:
    configured = os.environ.get("CAPIVARA_CATALOG_POLICY_ROOT", "").strip()
    return Path(configured).resolve() if configured else (Path(root) / "config" / "catalog-runtime").resolve()


def _runtime_path(root: Path, runtime_id: str) -> Path:
    runtime_id = str(runtime_id or "").strip()
    if not _RUNTIME_ID.fullmatch(runtime_id):
        raise ValueError("valid runtime_id is required")
    base = _state_root(root)
    path = (base / f"{runtime_id}.json").resolve()
    path.relative_to(base)
    return path


def default_policy(runtime: dict[str, Any]) -> dict[str, Any]:
    process = runtime.get("process") if isinstance(runtime.get("process"), dict) else {}
    executable = str(process.get("executable") or "").strip()
    arguments = process.get("args") if isinstance(process.get("args"), list) else []
    return {
        "schema_version": 1,
        "kind": "CatalogRuntimePolicy",
        "runtime_id": str(runtime.get("id") or ""),
        "executable": executable,
        "arguments": [str(v) for v in arguments],
        "working_directory": ".",
        "environment": {},
        "shutdown": {"mode": "signal", "value": "TERM"},
        "start_timeout_seconds": 120,
        "stop_timeout_seconds": 30,
        "variables": [],
        "templates": [],
    }


def validate_policy(payload: dict[str, Any], *, runtime_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("policy must be an object")
    result = dict(payload)
    result["schema_version"] = 1
    result["kind"] = "CatalogRuntimePolicy"
    result["runtime_id"] = str(runtime_id)
    executable = str(result.get("executable") or "").strip()
    if not executable or "\x00" in executable or "\n" in executable or "\r" in executable or len(executable) > 512:
        raise ValueError("invalid executable")
    result["executable"] = executable
    arguments = result.get("arguments", [])
    if not isinstance(arguments, list) or len(arguments) > 128:
        raise ValueError("invalid arguments")
    result["arguments"] = []
    for value in arguments:
        text = str(value)
        if "\x00" in text or "\n" in text or "\r" in text or len(text) > 4096:
            raise ValueError("invalid argument")
        result["arguments"].append(text)
    working = str(result.get("working_directory") or ".").strip()
    if Path(working).is_absolute() or ".." in Path(working).parts or "\x00" in working:
        raise ValueError("working_directory must stay inside the instance")
    result["working_directory"] = working or "."
    environment = result.get("environment", {})
    if not isinstance(environment, dict) or len(environment) > 128:
        raise ValueError("invalid environment")
    normalized_env: dict[str, str] = {}
    for key, value in environment.items():
        name, text = str(key), str(value)
        if not _ENV_NAME.fullmatch(name) or "\x00" in text or "\n" in text or "\r" in text or len(text) > 4096:
            raise ValueError("invalid environment entry")
        normalized_env[name] = text
    result["environment"] = normalized_env
    for field, default, minimum, maximum in (("start_timeout_seconds", 120, 5, 3600), ("stop_timeout_seconds", 30, 1, 600)):
        try:
            value = int(result.get(field, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {field}") from exc
        if not minimum <= value <= maximum:
            raise ValueError(f"invalid {field}")
        result[field] = value
    shutdown = result.get("shutdown") or {"mode": "signal", "value": "TERM"}
    if not isinstance(shutdown, dict) or str(shutdown.get("mode") or "signal") not in {"signal", "command", "stdin"}:
        raise ValueError("invalid shutdown policy")
    result["shutdown"] = {"mode": str(shutdown.get("mode") or "signal"), "value": str(shutdown.get("value") or "TERM")[:1024]}
    variables = result.get("variables", [])
    if not isinstance(variables, list) or len(variables) > 128:
        raise ValueError("invalid variables")
    normalized_variables = []
    for item in variables:
        if not isinstance(item, dict):
            raise ValueError("invalid variable")
        name = str(item.get("name") or "").strip()
        if not _VAR_NAME.fullmatch(name):
            raise ValueError("invalid variable name")
        normalized_variables.append({"name": name, "default": str(item.get("default") or ""), "required": bool(item.get("required", False)), "description": str(item.get("description") or "")[:500]})
    result["variables"] = normalized_variables
    templates = result.get("templates", [])
    if not isinstance(templates, list) or len(templates) > 128:
        raise ValueError("invalid templates")
    normalized_templates = []
    for item in templates:
        if not isinstance(item, dict):
            raise ValueError("invalid template")
        relative = str(item.get("path") or "").strip().replace("\\", "/")
        candidate = Path(relative)
        if not relative or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("template path must stay inside the instance")
        content = str(item.get("content") or "")
        if len(content.encode("utf-8")) > _MAX_TEMPLATE_BYTES:
            raise ValueError("template exceeds 1 MiB")
        normalized_templates.append({"path": relative, "content": content, "mode": str(item.get("mode") or "0644")})
    result["templates"] = normalized_templates
    return result


def load_policy(root: Path, runtime: dict[str, Any]) -> dict[str, Any]:
    runtime_id = str(runtime.get("id") or "").strip()
    path = _runtime_path(root, runtime_id)
    policy = default_policy(runtime)
    if path.is_file():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            policy.update(stored)
    return validate_policy(policy, runtime_id=runtime_id)


def save_policy(root: Path, runtime_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    policy = validate_policy(payload, runtime_id=runtime_id)
    path = _runtime_path(root, runtime_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(policy, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    return policy


__all__ = ["default_policy", "load_policy", "save_policy", "validate_policy"]
