#!/usr/bin/env python3
"""Apply Controller-resolved Catalog runtime policies on a Linux Agent."""
from __future__ import annotations

import os
import re
import shutil
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
    values.setdefault("INSTANCE_STATE_ROOT", str(context.get("instance_state_root") or ""))
    values.setdefault("CONTENT_ROOT", str(context.get("content_root") or context.get("install_path") or ""))
    values.setdefault("MEMORY_MB", str((context.get("resource_profile") or {}).get("memory_mb") or ""))
    ports = context.get("ports") if isinstance(context.get("ports"), dict) else {}
    for role, item in ports.items():
        if isinstance(item, dict) and item.get("port"):
            values[f"PORT_{str(role).upper().replace('-', '_')}"] = str(item["port"])
    if "PORT_STEAM_QUERY" not in values and "PORT_GAME_AUX" in values:
        values["PORT_STEAM_QUERY"] = values["PORT_GAME_AUX"]
    return values


def render(text: Any, values: dict[str, str]) -> str:
    raw = str(text)
    def repl(match):
        name = match.group(1) or match.group(2)
        if name not in values:
            raise ValueError(f"unresolved runtime variable: {name}")
        return values[name]
    return _TOKEN.sub(repl, raw)


def _argument_key(value: str) -> str:
    text = str(value)
    if text.startswith("-") and "=" in text:
        return text.split("=", 1)[0].lower()
    return text.lower()


def _merge_arguments(required: list[Any], policy_arguments: list[Any], values: dict[str, str]) -> list[str]:
    merged = [str(item) for item in required]
    owned = {_argument_key(item) for item in merged}
    for item in policy_arguments:
        rendered = render(item, values)
        key = _argument_key(rendered)
        if key in owned:
            continue
        merged.append(rendered)
        owned.add(key)
    return merged


def _resolve_executable(executable: str, content_root: Path) -> str:
    if executable == "@java":
        java = shutil.which("java")
        if not java:
            raise RuntimeError("Java is not available on this Agent")
        return str(Path(java).resolve())
    executable_path = Path(executable)
    return str(executable_path if executable_path.is_absolute() else (content_root / executable_path).resolve())


def apply_policy(spec: dict[str, Any], instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    policy = context.get("catalog_runtime_policy")
    if not isinstance(policy, dict) or not policy:
        return spec
    result = dict(spec)
    values = _values(instance, context, policy)
    content_root = Path(str(context.get("content_root") or context.get("install_path") or result.get("working_directory"))).resolve()
    executable = render(policy.get("executable") or Path(str(result["executable"])).name, values)
    result["executable"] = _resolve_executable(executable, content_root)
    policy_arguments = policy.get("arguments") if isinstance(policy.get("arguments"), list) else []
    result["arguments"] = _merge_arguments(list(result.get("arguments") or []), policy_arguments, values)
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
    result["catalog_network_properties"] = list(policy.get("network_properties") or [])
    result["catalog_variables"] = values
    return result


def _configuration_root(spec: dict[str, Any]) -> Path:
    return Path(str(spec.get("configuration_root") or spec.get("working_directory") or spec.get("path") or "")).resolve()


def materialize_templates(spec: dict[str, Any]) -> list[str]:
    templates = spec.get("catalog_templates") if isinstance(spec.get("catalog_templates"), list) else []
    if not templates:
        return []
    root = _configuration_root(spec)
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


def materialize_network_properties(spec: dict[str, Any]) -> list[str]:
    properties = spec.get("catalog_network_properties") if isinstance(spec.get("catalog_network_properties"), list) else []
    root = _configuration_root(spec)
    values = dict(spec.get("catalog_variables") or {})
    written: list[str] = []
    for item in properties:
        if not isinstance(item, dict):
            continue
        relative = Path(str(item.get("path") or ""))
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid network property path")
        target = (root / relative).resolve()
        target.relative_to(root)
        if target.is_symlink():
            raise ValueError("network property file cannot be a symbolic link")
        key = str(item.get("key") or "")
        value = render(item.get("value") or "", values)
        syntax = str(item.get("syntax") or "equals")
        separator = r"\s*=\s*"
        pattern = re.compile(rf"(?m)^\s*{re.escape(key)}{separator}[^\r\n;]*(?:;)?\s*$")
        line = f"{key} = {value};" if syntax == "semicolon" else f"{key}={value}"
        text = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        text = pattern.sub(line, text, count=1) if pattern.search(text) else text.rstrip("\n") + ("\n" if text else "") + line + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(relative.as_posix())
    return written


__all__ = ["apply_policy", "materialize_network_properties", "materialize_templates", "render"]
