#!/usr/bin/env python3
"""HTTP dispatchers and composition for Region/Datacenter administration."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

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


def _backend(legacy):
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def install_location_administration(legacy, authenticate) -> None:
    """Install topology administration on the active dashboard handler."""
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path not in {REGIONS_PATH, DATACENTERS_PATH}:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        query = parse_qs(parsed.query)
        active_value = str((query.get("active_only") or [""])[0]).strip().lower()
        result = dispatch_location_admin_get(
            parsed.path,
            user=user,
            backend=_backend(legacy),
            region_id=str((query.get("region_id") or [""])[0]).strip() or None,
            active_only=active_value in {"1", "true", "yes", "on"},
        )
        if result is None:
            return previous_get(self)
        status, body = result
        self.send_json(status, body)

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path not in {REGIONS_PATH, DATACENTERS_PATH}:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(
                400,
                {"error": "invalid_request", "message": "Requisição inválida."},
            )
            return
        result = dispatch_location_admin_post(
            parsed.path,
            payload,
            user=user,
            backend=_backend(legacy),
        )
        if result is None:
            return previous_post(self)
        status, body = result
        self.send_json(status, body)

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = [
    "REGIONS_PATH",
    "DATACENTERS_PATH",
    "dispatch_location_admin_get",
    "dispatch_location_admin_post",
    "install_location_administration",
]
