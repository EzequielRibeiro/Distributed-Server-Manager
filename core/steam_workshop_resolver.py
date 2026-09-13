#!/usr/bin/env python3
"""Safe Controller-side Steam Workshop reference and metadata resolver."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

STEAM_PUBLISHED_FILE_DETAILS_URL = (
    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
)
_ID_RE = re.compile(r"^[1-9][0-9]{0,19}$")
_CANONICAL_RE = re.compile(r"^([1-9][0-9]{0,9}):([1-9][0-9]{0,19})$")
_ALLOWED_HOSTS = frozenset({"steamcommunity.com", "www.steamcommunity.com"})
_ALLOWED_PATHS = frozenset({"/sharedfiles/filedetails/", "/workshop/filedetails/"})
_MAX_RESPONSE_BYTES = 1024 * 1024


class SteamWorkshopError(ValueError):
    pass


def _numeric(value: Any, label: str, pattern: re.Pattern[str] = _ID_RE) -> str:
    text = str(value or "").strip()
    if not pattern.fullmatch(text):
        raise SteamWorkshopError(f"invalid {label}")
    return text


def normalize_published_file_id(value: Any, *, expected_app_id: Any | None = None) -> str:
    """Normalize a raw PublishedFileId, canonical AppID:ID or official Workshop URL."""
    text = str(value or "").strip()
    if _ID_RE.fullmatch(text):
        return text

    canonical = _CANONICAL_RE.fullmatch(text)
    if canonical:
        if expected_app_id is not None and canonical.group(1) != _numeric(expected_app_id, "Workshop AppID"):
            raise SteamWorkshopError("Workshop AppID does not match this runtime")
        return canonical.group(2)

    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError as exc:
        raise SteamWorkshopError("invalid Steam Workshop URL") from exc
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in _ALLOWED_HOSTS:
        raise SteamWorkshopError("only official HTTPS Steam Workshop URLs are allowed")
    path = parsed.path.rstrip("/") + "/"
    if path not in _ALLOWED_PATHS or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise SteamWorkshopError("invalid Steam Workshop URL")
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    ids = params.get("id") or []
    if len(ids) != 1:
        raise SteamWorkshopError("Steam Workshop URL must contain one PublishedFileId")
    return _numeric(ids[0], "PublishedFileId")


def _default_transport(published_file_id: str) -> Mapping[str, Any]:
    payload = urllib.parse.urlencode({
        "itemcount": "1",
        "publishedfileids[0]": published_file_id,
    }).encode("ascii")
    request = urllib.request.Request(
        STEAM_PUBLISHED_FILE_DETAILS_URL,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Capivara-DSM/SteamWorkshopResolver",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except Exception as exc:
        raise SteamWorkshopError("Steam Workshop metadata lookup failed") from exc
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise SteamWorkshopError("Steam Workshop metadata response is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SteamWorkshopError("invalid Steam Workshop metadata response") from exc
    if not isinstance(value, Mapping):
        raise SteamWorkshopError("invalid Steam Workshop metadata response")
    return value


def resolve_workshop_item(
    reference: Any,
    *,
    expected_app_id: Any,
    transport: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve public Workshop metadata and verify it belongs to the runtime's game AppID."""
    app_id = _numeric(expected_app_id, "Workshop AppID")
    published_file_id = normalize_published_file_id(reference, expected_app_id=app_id)
    response = (transport or _default_transport)(published_file_id)
    details = ((response.get("response") or {}).get("publishedfiledetails") or []) if isinstance(response, Mapping) else []
    if len(details) != 1 or not isinstance(details[0], Mapping):
        raise SteamWorkshopError("Steam Workshop item was not found")
    detail = details[0]
    if int(detail.get("result") or 0) != 1:
        raise SteamWorkshopError("Steam Workshop item was not found")
    returned_id = _numeric(detail.get("publishedfileid"), "PublishedFileId")
    if returned_id != published_file_id:
        raise SteamWorkshopError("Steam Workshop response identity mismatch")
    consumer_app_id = _numeric(detail.get("consumer_app_id"), "consumer AppID")
    if consumer_app_id != app_id:
        raise SteamWorkshopError("Steam Workshop item does not belong to this game")

    metadata: dict[str, Any] = {
        "published_file_id": published_file_id,
        "consumer_app_id": app_id,
    }
    title = str(detail.get("title") or "").strip()
    if title:
        metadata["title"] = title[:500]
    creator = str(detail.get("creator") or "").strip()
    if creator.isdigit():
        metadata["creator"] = creator[:32]
    for key in ("time_created", "time_updated"):
        try:
            number = int(detail.get(key))
        except (TypeError, ValueError):
            continue
        if number >= 0:
            metadata[key] = number

    return {
        "provider": "steam-workshop",
        "package_id": f"{app_id}:{published_file_id}",
        "published_file_id": published_file_id,
        "consumer_app_id": app_id,
        "metadata": metadata,
    }


__all__ = [
    "STEAM_PUBLISHED_FILE_DETAILS_URL",
    "SteamWorkshopError",
    "normalize_published_file_id",
    "resolve_workshop_item",
]
