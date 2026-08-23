#!/usr/bin/env python3
"""Apply Controller-resolved Catalog runtime policies on a Linux Agent."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"\{\{([A-Z][A-Z0-9_]{0,63})\}\}|\$\{([A-Z][A-Z0-9_]{0,63})\}")


def _values(instance: dict[str, Any], context: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in policy.get("variables") or []:
        if isinstance(item, dict) and item.get("name"):
            values[str(item["name"])] = str(item.get("default") or "")
    for source in (context.get("variables"), context.get("runtime_variables")):
        if isinstance(source, dict):
            values.update({str(k): str(v) for k, v in source.items()})
    values.setdefault("INSTANCE_ID", str(instance.get("instance_id") or ""))
    values.setdefault("GAME_ID", str(instance.get("game_id") or ""))
    values.setdefault("MEMORY_MB", str((context.get("resource_profile") or {}).get("memory_mb") or ""))
    ports = context.get("ports") if isinstance(context.get("ports"), dict) else {}
    for role, item in ports.items():
        if isinstance(item, dict) and item.get("port"):
            values[f"PORT_{str(role).upper().replace('-', '_')}"] = str(item["port"])
    return values


def render(text: Any, values: dict[str, str]) -> str:
    raw = str(text)
    def repl(match):
        name = match.group(1) or match.group(2)
        if name not in values:
            raise ValueError(f"unresolved runtime variable: {name}")
        return values[name]
    return _TOKEN.sub(repl, raw)


def apply_policy(spec: dict[str, Any], instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    policy = context.get("catalog_runtime_policy")
    if not isinstance(policy, dict) or not policy:
        return spec
    result = dict(spec)
    values = _values(instance, context, policy)
    content_root = Path(str(context.get("content_root") or context.get("install_path") or result.get("working_directory"))).resolve()
    executable = render(policy.get("executable") or Path(str(result["executable"])).name, values)
    executable_path = Path(executable)
    result["executable"] = str(executable_path if executable_path.is_absolute() else (content_root / executable_path).resolve())
    arguments = policy.get("arguments") if isinstance(policy.get("arguments"), list) else result.get("arguments", [])
    result["arguments"] = [render(value, values) for value in arguments]
    environment = dict(result.get("environment") or {})
    for key, value in (policy.get("environment") or {}).items():
        environment[str(key)] = render(value, values)
    result["environment"] = environment
    result["catalog_runtime_policy"] = {
        "runtime_id": policy.get("runtime_id"),
        "shutdown": policy.get("shutdown"),
        "start_timeout_seconds": policy.get("start_timeout_seconds"),
        "stop_timeout_seconds": policy.get("stop_timeout_seconds"),
    }
    result["catalog_templates"] = list(policy.get("templates") or [])
    result["catalog_variables"] = values
    return result


def materialize_templates(spec: dict[str, Any]) -> list[str]:
    templates = spec.get("catalog_templates") if isinstance(spec.get("catalog_templates"), list) else []
    if not templates:
        return []
    root = Path(str(spec.get("working_directory") or spec.get("path") or "")).resolve()
    values = dict(spec.get("catalog_variables") or {})
    written: list[str] = []
    for item in templates:
        if not isinstance(item, dict):
            continue
        relative = Path(str(item.get("path") or ""))
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid catalog template path")
        target = (root / relative).resolve()
        target.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = render(item.get("content") or "", values)
        target.write_text(content, encoding="utf-8")
        try:
            os.chmod(target, int(str(item.get("mode") or "0644"), 8))
        except (OSError, ValueError):
            os.chmod(target, 0o644)
        written.append(relative.as_posix())
    return written


__all__ = ["apply_policy", "materialize_templates", "render"]
