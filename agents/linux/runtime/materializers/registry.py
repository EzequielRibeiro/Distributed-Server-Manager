#!/usr/bin/env python3
"""Allowlisted registry for instance runtime materializers."""

from __future__ import annotations

from typing import Any

from .base import InstanceRuntimeMaterializer, MaterializerError
from .systemd import SystemdMaterializer

_MATERIALIZERS = {"systemd": SystemdMaterializer}


def resolve_materializer(spec: dict[str, Any]) -> InstanceRuntimeMaterializer:
    name = str(spec.get("adapter") or "").strip().lower()
    factory = _MATERIALIZERS.get(name)
    if factory is None:
        raise MaterializerError(f"unsupported runtime materializer: {name or 'unconfigured'}")
    return factory()


def supported_materializers() -> tuple[str, ...]:
    return tuple(sorted(_MATERIALIZERS))


__all__ = ["resolve_materializer", "supported_materializers"]
