from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any


def render(value: Any, values: dict[str, Any]) -> str:
    text = str(value)
    for key, replacement in values.items():
        text = text.replace("{{" + str(key) + "}}", str(replacement))
    return text


def _configuration_root(spec: dict[str, Any]) -> Path:
    raw = str(spec.get("configuration_root") or spec.get("instance_state_root") or spec.get("working_directory") or spec.get("path") or "").strip()
    if not raw:
        raise ValueError("runtime configuration root is unavailable")
    return Path(raw).resolve()


def apply_policy(spec: dict[str, Any], instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    result = dict(spec)
    policy = context.get("catalog_runtime_policy") if isinstance(context.get("catalog_runtime_policy"), dict) else {}
    network = policy.get("network") if isinstance(policy.get("network"), dict) else {}
    values = dict(result.get("catalog_variables") or {})
    ports = context.get("ports") if isinstance(context.get("ports"), dict) else {}
    for name, binding in ports.items():
        if isinstance(binding, dict) and binding.get("port") is not None:
            values[f"PORT_{str(name).upper()}"] = int(binding["port"])
    result["catalog_variables"] = values
    properties = result.get("catalog_network_properties") if isinstance(result.get("catalog_network_properties"), list) else []
    if isinstance(network.get("properties"), list):
        properties = [*properties, *network["properties"]]
    result["catalog_network_properties"] = properties
    return result


def materialize_templates(spec: dict[str, Any]) -> list[str]:
    templates = spec.get("templates") if isinstance(spec.get("templates"), list) else []
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
            raise ValueError("invalid runtime template path")
        target = (root / relative).resolve()
        target.relative_to(root)
        if target.is_symlink():
            raise ValueError("runtime template file cannot be a symbolic link")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(item.get("content") or "", values), encoding="utf-8")
        written.append(relative.as_posix())
    return written


def _ue_option_bounds(text: str) -> tuple[int, int]:
    match = re.search(r"(?<![A-Za-z0-9_])OptionSettings\s*=\s*\(", text)
    if not match:
        raise ValueError("Unreal OptionSettings entry is unavailable")
    body_start = match.end()
    depth = 1
    quoted = False
    escaped = False
    for index in range(body_start, len(text)):
        ch = text[index]
        if escaped:
            escaped = False
            continue
        if ch == "\\" and quoted:
            escaped = True
            continue
        if ch == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return body_start, index
    raise ValueError("Unreal OptionSettings entry is malformed")


def _set_ue_option_setting(text: str, key: str, value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ValueError("invalid Unreal OptionSettings key")
    start, end = _ue_option_bounds(text)
    body = text[start:end]
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(key)}\s*=\s*(?:\"(?:\\.|[^\"])*\"|[^,)]*)")
    replacement = f"{key}={value}"
    if pattern.search(body):
        body = pattern.sub(replacement, body, count=1)
    else:
        body = body.rstrip()
        body = f"{body},{replacement}" if body else replacement
    return text[:start] + body + text[end:]


def _seed_network_property_target(spec: dict[str, Any], item: dict[str, Any], target: Path) -> None:
    seed_from = str(item.get("seed_from") or "").strip()
    if not seed_from:
        return
    if target.exists():
        if not target.is_file():
            raise ValueError("network property target is not a regular file")
        # Palworld and similar runtimes may create an empty placeholder config
        # before Capivara has a chance to seed the vendor default. Treat only an
        # empty/whitespace-only file as uninitialized; never overwrite real
        # customer configuration.
        if target.read_text(encoding="utf-8", errors="replace").strip():
            return
    relative = Path(seed_from)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid network property seed path")
    working_root = Path(str(spec.get("working_directory") or spec.get("path") or "")).resolve()
    source = (working_root / relative).resolve()
    source.relative_to(working_root)
    if source.is_symlink() or not source.is_file():
        raise ValueError("network property seed file is unavailable")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


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
        _seed_network_property_target(spec, item, target)
        key = str(item.get("key") or "")
        value = render(item.get("value") or "", values)
        syntax = str(item.get("syntax") or "equals")
        text = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        if syntax == "ue_option_settings":
            text = _set_ue_option_setting(text, key, value)
        else:
            separator = r"\s*=\s*"
            pattern = re.compile(rf"(?m)^\s*{re.escape(key)}{separator}[^\r\n;]*(?:;)?\s*$")
            line = f"{key} = {value};" if syntax == "semicolon" else f"{key}={value}"
            text = pattern.sub(line, text, count=1) if pattern.search(text) else text.rstrip("\n") + ("\n" if text else "") + line + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(relative.as_posix())
    return written


__all__ = ["apply_policy", "materialize_network_properties", "materialize_templates", "render"]