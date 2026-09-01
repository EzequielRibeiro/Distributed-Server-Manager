#!/usr/bin/env python3
"""Discover and validate immutable Capivara Agent releases on GitHub."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_REPOSITORY = "EzequielRibeiro/Distributed-Server-Manager"
DEFAULT_API = "https://api.github.com"
DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_STALE_TTL_SECONDS = 3600
_TAG_RE = re.compile(r"^v?[0-9][A-Za-z0-9._+-]{0,63}$")
_CACHE: dict[str, tuple[float, Any]] = {}


class AgentReleaseError(RuntimeError):
    """Administrator-facing GitHub release discovery failure."""


def _asset_names(release: dict[str, Any]) -> set[str]:
    return {
        str(asset.get("name", ""))
        for asset in (release.get("assets") or [])
        if isinstance(asset, dict)
    }


def _platform_assets(tag: str, platform: str) -> tuple[str, str]:
    version = str(tag).strip().lstrip("v")
    if platform == "linux":
        archive = f"capivara-agent-linux-{version}.tar.gz"
    elif platform == "windows":
        archive = f"capivara-agent-windows-{version}.zip"
    else:
        raise ValueError("unsupported Agent platform")
    return archive, archive + ".sha256"


def release_supports_platform(release: dict[str, Any], platform: str) -> bool:
    tag = str(release.get("tag_name", "")).strip()
    if not tag:
        return False
    archive, checksum = _platform_assets(tag, platform)
    names = _asset_names(release)
    return archive in names and checksum in names


def _cache_ttl(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _request_json(path: str, *, timeout: int = 8) -> Any:
    api = os.environ.get("CAPIVARA_GITHUB_API", DEFAULT_API).rstrip("/")
    repository = os.environ.get("CAPIVARA_GITHUB_REPO", DEFAULT_REPOSITORY).strip()
    url = f"{api}/repos/{repository}/{path.lstrip('/')}"
    now = time.monotonic()
    ttl = _cache_ttl("CAPIVARA_GITHUB_RELEASE_CACHE_TTL", DEFAULT_CACHE_TTL_SECONDS)
    stale_ttl = max(ttl, _cache_ttl("CAPIVARA_GITHUB_RELEASE_STALE_TTL", DEFAULT_STALE_TTL_SECONDS))
    cached = _CACHE.get(url)
    if cached and now - cached[0] <= ttl:
        return cached[1]

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Capivara-DSM-Agent-Release-Service",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = str(os.environ.get("CAPIVARA_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            _CACHE[url] = (now, payload)
            return payload
    except HTTPError as exc:
        if cached and now - cached[0] <= stale_ttl and exc.code in {403, 429, 500, 502, 503, 504}:
            return cached[1]
        if exc.code == 404:
            raise AgentReleaseError("GitHub release not found") from exc
        if exc.code in {403, 429}:
            raise AgentReleaseError("GitHub release API rate limit reached; retry after the cache refresh interval") from exc
        raise AgentReleaseError(f"GitHub release API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        if cached and now - cached[0] <= stale_ttl:
            return cached[1]
        raise AgentReleaseError(f"Unable to query GitHub releases: {exc}") from exc


def list_agent_releases(
    platform: str,
    *,
    include_prereleases: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    platform = str(platform or "linux").strip().lower()
    if platform not in {"linux", "windows"}:
        raise ValueError("unsupported Agent platform")
    releases = _request_json(f"releases?per_page={max(1, min(int(limit), 50))}")
    if not isinstance(releases, list):
        raise AgentReleaseError("GitHub release API returned an invalid response")

    result: list[dict[str, Any]] = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        if release.get("prerelease") and not include_prereleases:
            continue
        if not release_supports_platform(release, platform):
            continue
        tag = str(release.get("tag_name", "")).strip()
        result.append(
            {
                "tag": tag,
                "name": str(release.get("name") or tag),
                "published_at": release.get("published_at"),
                "prerelease": bool(release.get("prerelease")),
                "html_url": release.get("html_url"),
            }
        )
    return result


def resolve_agent_release(tag: str | None, platform: str) -> dict[str, Any]:
    platform = str(platform or "linux").strip().lower()
    requested = str(tag or "latest").strip()
    if requested in {"", "latest"}:
        releases = list_agent_releases(platform, include_prereleases=False, limit=30)
        if not releases:
            raise AgentReleaseError(
                f"No stable GitHub release contains the required {platform} Agent package and checksum"
            )
        return releases[0]

    if not _TAG_RE.fullmatch(requested):
        raise ValueError("invalid Agent release tag")
    release = _request_json(f"releases/tags/{requested}")
    if not isinstance(release, dict) or release.get("draft"):
        raise AgentReleaseError(f"Agent release {requested} is not available")
    if not release_supports_platform(release, platform):
        raise AgentReleaseError(
            f"Agent release {requested} does not contain the required {platform} package and checksum"
        )
    return {
        "tag": str(release.get("tag_name", requested)),
        "name": str(release.get("name") or requested),
        "published_at": release.get("published_at"),
        "prerelease": bool(release.get("prerelease")),
        "html_url": release.get("html_url"),
    }


__all__ = [
    "AgentReleaseError",
    "list_agent_releases",
    "release_supports_platform",
    "resolve_agent_release",
]
