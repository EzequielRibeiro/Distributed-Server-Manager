#!/usr/bin/env python3
"""Contract and helpers for game-specific runtime profiles."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ProfileError(ValueError):
    pass


def require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text or "\n" in text or "\r" in text:
        raise ProfileError(f"invalid {label}")
    return text


def require_absolute(value: Any, label: str) -> str:
    text = require_text(value, label)
    if not Path(text).is_absolute():
        raise ProfileError(f"invalid {label}")
    return str(Path(text))


def require_within(root: Any, value: Any, label: str) -> str:
    """Require an absolute path to remain inside the provisioned content root."""
    root_path = Path(require_absolute(root, "install_path")).resolve(strict=False)
    value_path = Path(require_absolute(value, label)).resolve(strict=False)
    try:
        value_path.relative_to(root_path)
    except ValueError as exc:
        raise ProfileError(f"{label} escapes provisioned content root") from exc
    return str(value_path)


def port_bindings(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize reserved ports supplied by provisioning without allocating any port."""
    raw = context.get("ports", {})
    values: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        entries = []
        for role, item in raw.items():
            if isinstance(item, dict):
                entries.append({"role": role, **item})
            else:
                entries.append({"role": role, "port": item})
    elif isinstance(raw, list):
        entries = raw
    else:
        raise ProfileError("invalid reserved ports")
    for item in entries:
        if not isinstance(item, dict):
            raise ProfileError("invalid reserved port entry")
        role = require_text(item.get("role") or item.get("name") or item.get("purpose"), "port role").lower()
        if role in values:
            raise ProfileError(f"duplicate reserved port role: {role}")
        try:
            port = int(item.get("port"))
        except (TypeError, ValueError) as exc:
            raise ProfileError(f"invalid reserved port for role: {role}") from exc
        if port < 1 or port > 65535:
            raise ProfileError(f"invalid reserved port for role: {role}")
        protocol = str(item.get("protocol") or "udp").strip().lower()
        if protocol not in {"tcp", "udp"}:
            raise ProfileError(f"invalid protocol for role: {role}")
        values[role] = {"port": port, "protocol": protocol}
    return values


def require_port(context: dict[str, Any], role: str, *, protocol: str | None = None) -> int:
    binding = port_bindings(context).get(role)
    if binding is None:
        raise ProfileError(f"required reserved port is missing: {role}")
    if protocol and binding["protocol"] != protocol:
        raise ProfileError(f"reserved port protocol mismatch for role: {role}")
    return int(binding["port"])


class GameRuntimeProfile(ABC):
    """Translate one game's structured provisioning context into a RuntimeSpec."""

    game_ids: tuple[str, ...] = ()
    profile_version: int = 1

    def migration_context(self, record: dict[str, Any]) -> dict[str, Any]:
        """Reconstruct the minimum safe context needed to rebuild a persisted spec.

        Profiles that have changed their runtime layout must override this method.
        Returning an empty object keeps migration opt-in for each game profile.
        """
        return {}

    @abstractmethod
    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


__all__ = [
    "GameRuntimeProfile", "ProfileError", "port_bindings", "require_absolute", "require_port", "require_text", "require_within",
]
