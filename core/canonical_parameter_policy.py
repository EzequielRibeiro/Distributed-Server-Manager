#!/usr/bin/env python3
"""Canonical runtime argument/environment normalization for Controller boundaries."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_MAX_ITEMS = 128
_MAX_VALUE_LENGTH = 4096


class ParameterPolicyError(ValueError):
    pass


def _safe_text(value: Any, label: str) -> str:
    text = str(value)
    if "\x00" in text or "\n" in text or "\r" in text or len(text) > _MAX_VALUE_LENGTH:
        raise ParameterPolicyError(f"invalid {label}")
    return text


def normalize_arguments(value: Any) -> list[str]:
    """Return canonical argv without shell parsing or concatenation.

    A legacy scalar Catalog ``process.args`` value is preserved as one opaque
    argument. Canonical distributed payloads always contain a list.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_ITEMS:
        raise ParameterPolicyError("invalid arguments")
    return [_safe_text(item, "runtime argument") for item in value]


def normalize_environment(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > _MAX_ITEMS:
        raise ParameterPolicyError("invalid environment")
    result: dict[str, str] = {}
    for key, raw in value.items():
        name = str(key)
        if not _ENV_NAME.fullmatch(name):
            raise ParameterPolicyError("invalid environment name")
        result[name] = _safe_text(raw, "environment value")
    return result


@dataclass(frozen=True)
class CanonicalParameterPolicy:
    arguments: tuple[str, ...] = ()
    environment_items: tuple[tuple[str, str], ...] = ()

    @property
    def environment(self) -> dict[str, str]:
        return dict(self.environment_items)

    def as_dict(self) -> dict[str, Any]:
        return {"arguments": list(self.arguments), "environment": self.environment}


def normalize_parameter_policy(payload: Mapping[str, Any] | None) -> CanonicalParameterPolicy:
    source = dict(payload or {})
    arguments = source.get("arguments")
    if arguments is None and "args" in source:
        arguments = source.get("args")
    environment = source.get("environment")
    if environment is None and "env" in source:
        environment = source.get("env")
    normalized_env = normalize_environment(environment)
    return CanonicalParameterPolicy(
        arguments=tuple(normalize_arguments(arguments)),
        environment_items=tuple(normalized_env.items()),
    )


def canonicalize_parameter_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy a policy/spec and emit only canonical parameter field names."""
    source = dict(payload or {})
    normalized = normalize_parameter_policy(source)
    source.pop("args", None)
    source.pop("env", None)
    source.update(normalized.as_dict())
    return source


__all__ = [
    "CanonicalParameterPolicy",
    "ParameterPolicyError",
    "canonicalize_parameter_payload",
    "normalize_arguments",
    "normalize_environment",
    "normalize_parameter_policy",
]
