#!/usr/bin/env python3
"""Canonical contracts for the Capivara Universal Configuration Platform."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

CONFIG_SCHEMA_VERSION = 1
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
SCOPES = frozenset({"global", "agent", "instance"})
SENSITIVE_TOKENS = ("password", "passwd", "secret", "token", "credential", "private_key")


class ConfigurationValidationError(ValueError):
    """Raised when configuration violates the stable C2 contract."""


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def checksum(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_secret_policy(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            name = str(key).strip().lower()
            child = f"{path}.{name}" if path else name
            if any(token in name for token in SENSITIVE_TOKENS):
                if name.endswith("_ref"):
                    if not isinstance(nested, str) or not nested.strip():
                        raise ConfigurationValidationError(f"{child} must be a non-empty secret reference")
                else:
                    raise ConfigurationValidationError(
                        f"raw secret-like field is forbidden: {child}; use a *_ref field"
                    )
            _validate_secret_policy(nested, child)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_secret_policy(nested, f"{path}[{index}]")


def normalize_configuration(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ConfigurationValidationError("configuration must be an object")
    scope_type = str(raw.get("scope_type") or "").strip().lower()
    if scope_type not in SCOPES:
        raise ConfigurationValidationError(f"unsupported scope_type: {scope_type}")
    scope_id = str(raw.get("scope_id") or "").strip() or None
    if scope_type == "global" and scope_id is not None:
        raise ConfigurationValidationError("global scope must not define scope_id")
    if scope_type != "global" and scope_id is None:
        raise ConfigurationValidationError(f"{scope_type} scope requires scope_id")
    namespace = str(raw.get("namespace") or "").strip().lower()
    if not NAMESPACE_RE.fullmatch(namespace):
        raise ConfigurationValidationError("namespace must use lowercase dotted/kebab notation")
    value = raw.get("value")
    if not isinstance(value, Mapping):
        raise ConfigurationValidationError("value must be an object")
    _validate_secret_policy(value)
    schema_version = int(raw.get("schema_version") or CONFIG_SCHEMA_VERSION)
    if schema_version != CONFIG_SCHEMA_VERSION:
        raise ConfigurationValidationError(f"unsupported configuration schema version: {schema_version}")
    normalized_value = dict(value)
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "kind": "CapivaraConfiguration",
        "scope_type": scope_type,
        "scope_id": scope_id,
        "namespace": namespace,
        "value": normalized_value,
        "checksum": checksum(normalized_value),
    }


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


__all__ = [
    "CONFIG_SCHEMA_VERSION", "ConfigurationValidationError", "SCOPES",
    "canonical_json", "checksum", "deep_merge", "normalize_configuration",
]
