#!/usr/bin/env python3
"""Controller-side persistent runtime/startup policy for Catalog runtimes."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from core.canonical_parameter_policy import normalize_arguments

_RUNTIME_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_VAR_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_PORT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_TEMPLATE_BYTES = 1024 * 1024

_SERVER_SETTING_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SERVER_SETTING_BINDING_KINDS = {"property", "json", "xml_property", "ini", "argument", "launch_option", "command_batch"}

def _normalize_server_settings(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("server_settings must be an object")
    raw_fields = raw.get("fields", {})
    if not isinstance(raw_fields, dict) or len(raw_fields) > 128:
        raise ValueError("invalid server_settings fields")
    fields: dict[str, dict[str, Any]] = {}
    for field_id, item in raw_fields.items():
        field_id = str(field_id).strip().lower()
        if not _SERVER_SETTING_KEY.fullmatch(field_id) or not isinstance(item, dict):
            raise ValueError("invalid server setting field")
        kind = str(item.get("type") or "string").strip().lower()
        if kind not in {"string", "integer", "boolean", "select"}:
            raise ValueError(f"invalid server setting type: {field_id}")
        binding = item.get("binding")
        if not isinstance(binding, dict):
            raise ValueError(f"server setting binding is required: {field_id}")
        binding_kind = str(binding.get("kind") or "property").strip().lower()
        if binding_kind not in _SERVER_SETTING_BINDING_KINDS:
            raise ValueError(f"invalid server setting binding: {field_id}")
        normalized_binding = {"kind": binding_kind}
        if binding_kind in {"property", "json", "xml_property", "ini"}:
            relative = str(binding.get("path") or "").strip().replace("\\", "/")
            candidate = Path(relative)
            if not relative or candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError(f"server setting path must stay inside configuration root: {field_id}")
            normalized_binding["path"] = relative
        if binding_kind == "property":
            key = str(binding.get("key") or "").strip()
            syntax = str(binding.get("syntax") or "equals").strip().lower()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}", key) or syntax not in {"equals", "semicolon", "command", "ue_option_settings"}:
                raise ValueError(f"invalid property binding: {field_id}")
            normalized_binding.update({"key": key, "syntax": syntax, "quote": str(binding.get("quote") or "none").lower()})
            activation = binding.get("activate_argument")
            if activation is not None:
                if not isinstance(activation, dict): raise ValueError(f"invalid activation argument: {field_id}")
                flag = str(activation.get("flag") or "").strip(); style = str(activation.get("style") or "equals").strip().lower()
                if not flag or style not in {"pair", "equals"} or any(ch in flag for ch in "\x00\r\n"):
                    raise ValueError(f"invalid activation argument: {field_id}")
                normalized_binding["activate_argument"] = {"flag": flag, "style": style}
        elif binding_kind == "json":
            keys = binding.get("keys")
            if isinstance(keys, str): keys = [part for part in keys.split(".") if part]
            if not isinstance(keys, list) or not keys or len(keys) > 16 or any(not str(part).strip() for part in keys):
                raise ValueError(f"invalid JSON binding: {field_id}")
            normalized_binding["keys"] = [str(part) for part in keys]
        elif binding_kind == "xml_property":
            key = str(binding.get("key") or "").strip()
            if not key or len(key) > 128: raise ValueError(f"invalid XML property binding: {field_id}")
            normalized_binding["key"] = key
        elif binding_kind == "ini":
            section, key = str(binding.get("section") or "").strip(), str(binding.get("key") or "").strip()
            if not section or not key or any(ch in section + key for ch in "\r\n[]="):
                raise ValueError(f"invalid INI binding: {field_id}")
            normalized_binding.update({"section": section, "key": key})
        elif binding_kind == "argument":
            flag = str(binding.get("flag") or "").strip()
            style = str(binding.get("style") or "pair").strip().lower()
            if not flag or any(ch in flag for ch in "\x00\r\n") or style not in {"pair", "equals"}:
                raise ValueError(f"invalid argument binding: {field_id}")
            normalized_binding.update({"flag": flag, "style": style})
        elif binding_kind == "launch_option":
            key = str(binding.get("key") or "").strip()
            try: index = int(binding.get("argument_index", 0))
            except (TypeError, ValueError) as exc: raise ValueError(f"invalid launch option binding: {field_id}") from exc
            if not key or index < 0 or index > 16: raise ValueError(f"invalid launch option binding: {field_id}")
            normalized_binding.update({"key": key, "argument_index": index})
        elif binding_kind == "command_batch":
            command = str(binding.get("command") or "").strip(); separator = str(binding.get("separator") or ","); before = str(binding.get("before") or "host").strip()
            try: index = int(binding.get("argument_index", 2))
            except (TypeError, ValueError) as exc: raise ValueError(f"invalid command batch binding: {field_id}") from exc
            if not command or index < 0 or index > 16 or separator != "," or any(ch in command + before for ch in "\x00\r\n,"):
                raise ValueError(f"invalid command batch binding: {field_id}")
            normalized_binding.update({"command": command, "argument_index": index, "separator": separator, "before": before})
        boolean_values = binding.get("boolean_values")
        if boolean_values is not None:
            if not isinstance(boolean_values, dict) or "true" not in boolean_values or "false" not in boolean_values:
                raise ValueError(f"invalid boolean_values: {field_id}")
            normalized_binding["boolean_values"] = {"true": str(boolean_values["true"]), "false": str(boolean_values["false"])}
        field = {
            "label": str(item.get("label") or field_id)[:128],
            "description": str(item.get("description") or "")[:500],
            "type": kind,
            "customer_editable": bool(item.get("customer_editable", True)),
            "binding": normalized_binding,
        }
        for name in ("default", "min", "max", "min_length", "max_length", "allowed"):
            if name in item: field[name] = item[name]
        if kind == "select" and (not isinstance(field.get("allowed"), list) or not field["allowed"]):
            raise ValueError(f"select server setting requires allowed values: {field_id}")
        fields[field_id] = field
    return {"restart_required": bool(raw.get("restart_required", True)), "fields": fields}

def _enforce_server_settings(runtime: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    result = dict(policy)
    result["server_settings"] = _normalize_server_settings(runtime.get("server_settings") or {})
    return result


def _network_variable_template(value: object) -> str:
    """Translate Catalog ``{role}`` placeholders to Agent runtime variables."""
    text = str(value)
    return re.sub(
        r"\{([a-z][a-z0-9_]{0,63})\}",
        lambda match: "{{PORT_" + match.group(1).upper() + "}}",
        text,
    )


def _catalog_network_exposure(runtime: dict[str, Any]) -> list[dict[str, str]]:
    network = runtime.get("network") if isinstance(runtime.get("network"), dict) else {}
    result: list[dict[str, str]] = []
    for item in network.get("ports") or []:
        if not isinstance(item, dict):
            continue
        result.append({
            "name": str(item.get("name") or ""),
            "protocol": str(item.get("protocol") or "").lower(),
            "exposure": str(item.get("exposure") or "none").lower(),
        })
    return result


def _enforce_network_policy(runtime: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Network bindings/exposure declared by Catalog cannot be removed by UI overrides."""
    result = dict(policy)
    arguments = list(result.get("arguments") or [])
    properties = [dict(item) for item in result.get("network_properties") or [] if isinstance(item, dict)]
    network = runtime.get("network") if isinstance(runtime.get("network"), dict) else {}
    for application in network.get("apply") or []:
        if not isinstance(application, dict):
            continue
        kind = str(application.get("kind") or "").strip().lower()
        if kind == "argument":
            required = _network_variable_template(application.get("template") or "")
            if required and required not in arguments:
                arguments.append(required)
        elif kind == "property":
            required = {
                "path": str(application.get("file") or ""),
                "key": str(application.get("key") or ""),
                "value": _network_variable_template(application.get("value") or ""),
                "syntax": str(application.get("syntax") or "equals"),
            }
            properties = [item for item in properties if (item.get("path"), item.get("key")) != (required["path"], required["key"])]
            properties.append(required)
    result["arguments"] = arguments
    result["network_properties"] = properties
    result["network_exposure"] = _catalog_network_exposure(runtime)
    return result


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
    arguments = normalize_arguments(process.get("args"))
    return _enforce_server_settings(runtime, _enforce_network_policy(runtime, {
        "schema_version": 1,
        "kind": "CatalogRuntimePolicy",
        "runtime_id": str(runtime.get("id") or ""),
        "executable": executable,
        "arguments": arguments,
        "working_directory": ".",
        "environment": {},
        "shutdown": {"mode": "signal", "value": "TERM"},
        "start_timeout_seconds": 120,
        "stop_timeout_seconds": 30,
        "variables": [],
        "templates": [],
        "network_properties": [],
        "network_exposure": [],
        "server_settings": {},
    }))


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
    properties = result.get("network_properties", [])
    if not isinstance(properties, list) or len(properties) > 128:
        raise ValueError("invalid network properties")
    normalized_properties = []
    for item in properties:
        if not isinstance(item, dict):
            raise ValueError("invalid network property")
        relative = str(item.get("path") or "").strip().replace("\\", "/")
        candidate = Path(relative)
        key = str(item.get("key") or "").strip()
        syntax = str(item.get("syntax") or "equals").strip().lower()
        if not relative or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("network property path must stay inside the instance")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}", key):
            raise ValueError("invalid network property key")
        if syntax not in {"equals", "semicolon", "command"}:
            raise ValueError("invalid network property syntax")
        normalized_properties.append({"path": relative, "key": key, "value": str(item.get("value") or ""), "syntax": syntax})
    result["network_properties"] = normalized_properties
    exposure = result.get("network_exposure", [])
    if not isinstance(exposure, list) or len(exposure) > 128:
        raise ValueError("invalid network exposure")
    normalized_exposure: list[dict[str, str]] = []
    seen_exposure: set[str] = set()
    for item in exposure:
        if not isinstance(item, dict):
            raise ValueError("invalid network exposure entry")
        name = str(item.get("name") or "").strip()
        protocol = str(item.get("protocol") or "").strip().lower()
        scope = str(item.get("exposure") or "none").strip().lower()
        if not _PORT_NAME.fullmatch(name) or name in seen_exposure:
            raise ValueError("invalid network exposure port name")
        if protocol not in {"tcp", "udp"}:
            raise ValueError("invalid network exposure protocol")
        if scope not in {"public", "private", "none"}:
            raise ValueError("invalid network exposure scope")
        normalized_exposure.append({"name": name, "protocol": protocol, "exposure": scope})
        seen_exposure.add(name)
    result["network_exposure"] = normalized_exposure
    result["server_settings"] = _normalize_server_settings(result.get("server_settings") or {})
    return result


def load_policy(root: Path, runtime: dict[str, Any]) -> dict[str, Any]:
    runtime_id = str(runtime.get("id") or "").strip()
    path = _runtime_path(root, runtime_id)
    policy = default_policy(runtime)
    if path.is_file():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            policy.update(stored)
    policy = _enforce_server_settings(runtime, _enforce_network_policy(runtime, policy))
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
