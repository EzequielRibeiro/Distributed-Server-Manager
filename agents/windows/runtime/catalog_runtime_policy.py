#!/usr/bin/env python3
"""Apply Controller-resolved Catalog runtime policies on a Windows Agent."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
_TOKEN = re.compile(r"\{\{([A-Z][A-Z0-9_]{0,63})\}\}|\$\{([A-Z][A-Z0-9_]{0,63})\}")

def render(text: Any, values: dict[str, str]) -> str:
    def replace(match):
        name = match.group(1) or match.group(2)
        if name not in values:
            raise ValueError(f"unresolved runtime variable: {name}")
        return values[name]
    return _TOKEN.sub(replace, str(text))

def apply_policy(spec: dict[str, Any], instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    policy = context.get("catalog_runtime_policy")
    if not isinstance(policy, dict) or not policy:
        return spec
    values = {str(item.get("name")): str(item.get("default") or "") for item in policy.get("variables", []) if isinstance(item, dict) and item.get("name")}
    values.update({str(k): str(v) for k, v in (context.get("runtime_variables") or {}).items()})
    values.setdefault("INSTANCE_ID", str(instance.get("instance_id") or ""))
    values.setdefault("GAME_ID", str(instance.get("game_id") or ""))
    values.setdefault("MEMORY_MB", str((context.get("resource_profile") or {}).get("memory_mb") or ""))
    for role, item in (context.get("ports") or {}).items():
        if isinstance(item, dict) and item.get("port"):
            values[f"PORT_{str(role).upper().replace('-', '_')}"] = str(item["port"])
    result = dict(spec)
    root = Path(str(context.get("content_root") or context.get("install_path") or result.get("working_directory"))).resolve()
    executable = Path(render(policy.get("executable") or Path(str(result["executable"])).name, values))
    result["executable"] = str(executable if executable.is_absolute() else (root / executable).resolve())
    result["arguments"] = [render(value, values) for value in policy.get("arguments", result.get("arguments", []))]
    environment = dict(result.get("environment") or {})
    environment.update({str(k): render(v, values) for k, v in (policy.get("environment") or {}).items()})
    result["environment"] = environment
    result["catalog_runtime_policy"] = {"runtime_id": policy.get("runtime_id"), "shutdown": policy.get("shutdown"), "start_timeout_seconds": policy.get("start_timeout_seconds"), "stop_timeout_seconds": policy.get("stop_timeout_seconds")}
    result["catalog_templates"] = list(policy.get("templates") or [])
    result["catalog_variables"] = values
    return result

__all__ = ["apply_policy", "render"]
