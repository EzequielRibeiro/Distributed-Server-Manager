#!/usr/bin/env python3
"""Allowlisted registry for Agent instance runtime adapters."""

from __future__ import annotations

from typing import Any

from .base import AdapterError, InstanceRuntimeAdapter
from .systemd import SystemdAdapter

_ADAPTERS = {
    "systemd": SystemdAdapter,
}


def resolve_adapter(instance: dict[str, Any]) -> InstanceRuntimeAdapter:
    name = str(instance.get("adapter") or "").strip().lower()
    factory = _ADAPTERS.get(name)
    if factory is None:
        raise AdapterError(f"unsupported instance runtime adapter: {name or 'unconfigured'}")
    return factory()


def supported_adapters() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


__all__ = ["resolve_adapter", "supported_adapters"]
