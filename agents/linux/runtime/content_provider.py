#!/usr/bin/env python3
"""Agent-local provider capability boundary for Universal Content.

This module owns acquisition only.  It never decides where content is activated;
`content_client` retains instance ownership, containment, atomic activation and
rollback.  Additional providers (for example Steam Workshop) register a local
resolver without teaching the reconciler game/provider-specific behavior.
"""
from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path
from typing import Any, Callable

Resolver = Callable[[dict[str, Any], Path, Path], Path]
_RESOLVERS: dict[str, Resolver] = {}


class ContentProviderCapabilityError(RuntimeError):
    pass


def _provider_name(value: Any) -> str:
    name = str(value or "").strip().lower()
    if not name or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in name):
        raise ValueError("invalid content provider")
    return name


def _controlled_local(raw: Any, game_data_root: Path) -> Path:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("resolved artifact path required")
    root = Path(game_data_root).resolve()
    candidate = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("local artifact outside game-data root") from exc
    if not candidate.exists():
        raise FileNotFoundError("local artifact missing")
    return candidate


def _local_resolver(artifact: dict[str, Any], stage: Path, game_data_root: Path) -> Path:
    del stage
    return _controlled_local(artifact.get("package_id") or artifact.get("path"), game_data_root)


def _https_resolver(artifact: dict[str, Any], stage: Path, game_data_root: Path) -> Path:
    del game_data_root
    url = str(artifact.get("url") or artifact.get("download_url") or "").strip()
    if not url.startswith("https://"):
        raise ValueError("remote content requires HTTPS")
    destination = stage / "artifact"
    request = urllib.request.Request(url, headers={"User-Agent": "Capivara-Agent/1"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 1024)
    return destination


def register_provider(name: str, resolver: Resolver, *, replace: bool = False) -> None:
    provider = _provider_name(name)
    if not callable(resolver):
        raise TypeError("content provider resolver must be callable")
    if provider in _RESOLVERS and not replace:
        raise ValueError(f"content provider already registered: {provider}")
    _RESOLVERS[provider] = resolver


def registered_providers() -> tuple[str, ...]:
    return tuple(sorted(_RESOLVERS))


def resolve_source(
    provider: str,
    artifact: dict[str, Any],
    stage: Path,
    game_data_root: Path,
) -> Path:
    provider = _provider_name(provider)
    artifact = dict(artifact or {})

    # `resolved_path` is the universal hand-off from a provider capability to
    # the reconciler.  It remains confined to the Agent game-data root.
    if artifact.get("resolved_path"):
        return _controlled_local(artifact["resolved_path"], game_data_root)

    resolver = _RESOLVERS.get(provider)
    if resolver is None:
        raise ContentProviderCapabilityError(
            f"{provider} content requires an Agent provider capability"
        )
    source = Path(resolver(artifact, Path(stage), Path(game_data_root))).resolve()
    if not source.exists():
        raise FileNotFoundError("content provider returned a missing artifact")
    return source


register_provider("local", _local_resolver)
for _remote_provider in ("http", "http-archive", "github", "modrinth"):
    register_provider(_remote_provider, _https_resolver)


__all__ = [
    "ContentProviderCapabilityError",
    "register_provider",
    "registered_providers",
    "resolve_source",
]
