#!/usr/bin/env python3
"""HTTP dispatchers for Region and Datacenter administration."""

from __future__ import annotations

from typing import Any

from location_admin_api import (
    list_datacenters_for_user,
    list_regions_for_user,
    upsert_datacenter_for_user,
    upsert_region_for_user,
)


REGIONS_PATH = "/api/infrastructure/regions"
DATACENTERS_PATH = "/api/infrastructure/datacenters"


def _error(exc: Exception) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, PermissionError):
        return 403, {"error": str(exc)}
    if isinstance(exc, ValueError):
        return 400, {"error": str(exc)}
    return 500, {"error": "failed to administer infrastructure topology"}


def dispatch_location_admin_get(
    path: str,
    *,
    user: dict[str, Any] | None,
    backend,
    region_id: str | None = None,
    active_only: bool = False,
) -> tuple[int, dict[str, Any]] | None:
    """Dispatch topology list endpoints."""
    try:
        if path == REGIONS_PATH:
            return 200, {
                "regions": list_regions_for_user(
                    user,
                    backend,
                    active_only=active_only,
                )
            }
        if path == DATACENTERS_PATH:
            return 200, {
                "datacenters": list_datacenters_for_user(
                    user,
                    backend,
                    region_id=region_id,
                    active_only=active_only,
                )
            }
        return None
    except Exception as exc:
        return _error(exc)


def dispatch_location_admin_post(
    path: str,
    payload: dict[str, Any] | None,
    *,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    """Dispatch Region/Datacenter create-or-edit endpoints."""
    try:
        if path == REGIONS_PATH:
            return 200, upsert_region_for_user(user, backend, payload)
        if path == DATACENTERS_PATH:
            return 200, upsert_datacenter_for_user(user, backend, payload)
        return None
    except Exception as exc:
        return _error(exc)
