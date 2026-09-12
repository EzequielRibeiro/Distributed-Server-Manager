#!/usr/bin/env python3
"""Canonical provider-resolution contract for Universal Content.

The Controller may describe *what* content is desired, but it never supplies a
shell command.  Agents resolve that description through capabilities installed
locally for their operating system/mode.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

OFFICIAL_CONTENT_PROVIDERS = frozenset({
    "github",
    "http",
    "http-archive",
    "local",
    "modrinth",
    "source-build",
    "steam",
    "steam-workshop",
})

_FORBIDDEN_ARTIFACT_KEYS = frozenset({"command", "shell", "exec", "script"})


class ContentProviderContractError(ValueError):
    pass


def normalize_provider_name(value: Any) -> str:
    provider = str(value or "").strip().lower()
    if not _PROVIDER.fullmatch(provider):
        raise ContentProviderContractError("invalid content provider")
    return provider


def provider_request(assignment: Mapping[str, Any]) -> dict[str, Any]:
    """Build the command-free request an Agent provider capability consumes."""
    if not isinstance(assignment, Mapping):
        raise ContentProviderContractError("content assignment must be an object")

    artifact_raw = assignment.get("artifact")
    artifact = dict(artifact_raw) if isinstance(artifact_raw, Mapping) else {}
    if _FORBIDDEN_ARTIFACT_KEYS.intersection(artifact):
        raise ContentProviderContractError("artifact may not contain executable commands")

    provider = normalize_provider_name(
        assignment.get("provider") or artifact.get("provider")
    )
    artifact["provider"] = provider

    content_type = str(assignment.get("content_type") or "other").strip().lower()
    package_id = str(
        artifact.get("package_id")
        or assignment.get("package_id")
        or artifact.get("url")
        or artifact.get("download_url")
        or artifact.get("path")
        or ""
    ).strip()

    # A resolved path is an Agent-local hand-off and remains constrained by the
    # reconciler's game-data root.  It is never interpreted as a command.
    resolved_path = str(artifact.get("resolved_path") or "").strip() or None
    if not package_id and not resolved_path:
        raise ContentProviderContractError("content provider package is required")

    return {
        "schema_version": 1,
        "kind": "CapivaraContentProviderRequest",
        "provider": provider,
        "content_type": content_type,
        "game_id": str(assignment.get("game_id") or "").strip().lower() or None,
        "content_id": str(assignment.get("content_id") or "").strip() or None,
        "version": str(assignment.get("version") or "latest").strip() or "latest",
        "package_id": package_id or None,
        "resolved_path": resolved_path,
        "artifact": artifact,
    }


def requires_agent_capability(request: Mapping[str, Any]) -> bool:
    """Return whether acquisition must be performed by an Agent capability."""
    provider = normalize_provider_name(request.get("provider"))
    return provider not in {"local"} and not bool(request.get("resolved_path"))


__all__ = [
    "ContentProviderContractError",
    "OFFICIAL_CONTENT_PROVIDERS",
    "normalize_provider_name",
    "provider_request",
    "requires_agent_capability",
]
