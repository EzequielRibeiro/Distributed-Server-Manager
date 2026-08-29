#!/usr/bin/env python3
"""Managed image assets for sandboxed game-profile presentations.

Images are embedded as validated data URLs inside the profile presentation. This
keeps the browser renderer network-isolated and lets a profile be cloned as a
complete reusable theme, including its artwork.
"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any

import catalog_resource_profiles_http as base

_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}
_ASSET_NAME = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
_DATA_URL = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\r\n]+)$")
MAX_ASSETS = 8
MAX_ASSET_BYTES = 2 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 8 * 1024 * 1024


def _normalize_asset(asset: Any) -> tuple[dict[str, str] | None, int]:
    if not isinstance(asset, dict):
        return None, 0
    name = str(asset.get("name") or "").strip()
    if not _ASSET_NAME.fullmatch(name):
        raise ValueError("presentation asset name must contain only letters, numbers, dot, dash or underscore")
    data_url = str(asset.get("data_url") or "").strip()
    match = _DATA_URL.fullmatch(data_url)
    if not match:
        raise ValueError("presentation asset must be PNG, JPEG or WebP")
    mime = match.group(1).lower()
    if mime not in _ALLOWED_MIME:
        raise ValueError("presentation asset type is not allowed")
    try:
        payload = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("presentation asset contains invalid base64 data") from exc
    if not payload:
        raise ValueError("presentation asset is empty")
    if len(payload) > MAX_ASSET_BYTES:
        raise ValueError("presentation asset exceeds the 2 MB limit")
    canonical = base64.b64encode(payload).decode("ascii")
    return {"name": name, "mime": mime, "data_url": f"data:{mime};base64,{canonical}"}, len(payload)


def normalize_presentation(item: Any) -> dict[str, Any] | None:
    """Drop-in replacement for the base presentation normalizer."""
    if not isinstance(item, dict):
        return None
    theme_id = str(item.get("theme_id") or "").strip().lower()
    if theme_id and not base._THEME_ID.fullmatch(theme_id):
        raise ValueError("presentation theme ID must be valid")
    html = base._sanitize_html_fragment(item.get("html"))
    css = base._sanitize_css(item.get("css"))
    assets = item.get("assets") if isinstance(item.get("assets"), list) else []
    normalized_assets: list[dict[str, str]] = []
    names: set[str] = set()
    total_bytes = 0
    for raw in assets[: MAX_ASSETS + 1]:
        if len(normalized_assets) >= MAX_ASSETS:
            raise ValueError(f"a profile presentation can contain at most {MAX_ASSETS} images")
        normalized, size = _normalize_asset(raw)
        if normalized is None:
            continue
        if normalized["name"] in names:
            raise ValueError("presentation asset names must be unique")
        names.add(normalized["name"])
        total_bytes += size
        if total_bytes > MAX_TOTAL_ASSET_BYTES:
            raise ValueError("profile presentation images exceed the 8 MB total limit")
        normalized_assets.append(normalized)
    if not (theme_id or html or css or normalized_assets):
        return None
    return {
        "theme_id": theme_id or None,
        "html": html,
        "css": css,
        "assets": normalized_assets,
    }


def install() -> None:
    base._normalize_presentation = normalize_presentation


__all__ = [
    "MAX_ASSETS",
    "MAX_ASSET_BYTES",
    "MAX_TOTAL_ASSET_BYTES",
    "install",
    "normalize_presentation",
]
