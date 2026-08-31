#!/usr/bin/env python3
"""Apply Controller-resolved Catalog runtime policies on a Windows Agent."""
from __future__ import annotations
import re
import shutil
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

def _resolve_executable(executable: str, root: Path) -> str:
    if executable == "@java":
        java = shutil.which("java.exe") or shutil.which("java")
        if not java:
            raise RuntimeError("Java is not available on this Agent")
        return str(Path(java).resolve())
    path = Path(executable)
    return str(path if path.is_absolute() else (root / path).resolve())

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
    if "PORT_STEAM_QUERY" not in values and "PORT_GAME_AUX" in values:
        values["PORT_STEAM_QUERY"] = values["PORT_GAME_AUX"]
    result = dict(spec)
    root = Path(str(context.get("content_root") or context.get("install_path") or result.get("working_directory"))).resolve()
    executable = render(policy.get("executable") or Path(str(result["executable"])).name, values)
    result["executable"] = _resolve_executable(executable, root)
    result["arguments"] = [render(value, values) for value in policy.get("arguments", result.get("arguments", []))]
    environment = dict(result.get("environment") or {})
    environment.update({str(k): render(v, values) for k, v in (policy.get("environment") or {}).items()})
    result["environment"] = environment
    result["catalog_runtime_policy"] = {"runtime_id": policy.get("runtime_id"), "shutdown": policy.get("shutdown"), "start_timeout_seconds": policy.get("start_timeout_seconds"), "stop_timeout_seconds": policy.get("stop_timeout_seconds")}
    result["catalog_templates"] = list(policy.get("templates") or [])
    result["catalog_network_properties"] = list(policy.get("network_properties") or [])
    result["catalog_variables"] = values
    return result

def materialize_network_properties(spec: dict[str, Any]) -> list[str]:
    root=Path(str(spec.get("working_directory") or spec.get("path") or "")).resolve();values=dict(spec.get("catalog_variables") or {});written=[]
    for item in spec.get("catalog_network_properties") or []:
        if not isinstance(item,dict):continue
        relative=Path(str(item.get("path") or ""))
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:raise ValueError("invalid network property path")
        target=(root/relative).resolve();target.relative_to(root)
        if target.is_symlink():raise ValueError("network property file cannot be a symbolic link")
        key=str(item.get("key") or "");value=render(item.get("value") or "",values);syntax=str(item.get("syntax") or "equals")
        pattern=re.compile(rf"(?m)^\s*{re.escape(key)}\s*=\s*[^\r\n;]*(?:;)?\s*$");line=f"{key} = {value};" if syntax=="semicolon" else f"{key}={value}"
        text=target.read_text(encoding="utf-8",errors="replace") if target.exists() else "";text=pattern.sub(line,text,count=1) if pattern.search(text) else text.rstrip("\n")+("\n" if text else "")+line+"\n"
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding="utf-8");written.append(relative.as_posix())
    return written

__all__ = ["apply_policy", "materialize_network_properties", "render"]
