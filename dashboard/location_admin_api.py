#!/usr/bin/env python3
"""RBAC-aware Region and Datacenter administration.

This module owns validation and administrative mutations for the geographic
placement hierarchy. Coordinates are optional and are never synthesized.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT_DIR / "database"
for path in (ROOT_DIR, DATABASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from infrastructure_repository import InfrastructureRepository
from location_repository import LocationRepository


VALID_STATUSES = {"active", "disabled"}


def _role(user: dict[str, Any] | None) -> str:
    if not user:
        raise PermissionError("authentication required")
    return str(user.get("role", "")).strip().lower()


def _require_reader(user: dict[str, Any] | None) -> None:
    if _role(user) not in {"admin", "controller"}:
        raise PermissionError("infrastructure topology is not permitted")


def _require_admin(user: dict[str, Any] | None) -> None:
    if _role(user) != "admin":
        raise PermissionError("infrastructure topology administration requires admin")


def _required_text(payload: dict[str, Any], name: str) -> str:
    value = str(payload.get(name, "")).strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _optional_text(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _country_code(payload: dict[str, Any]) -> str | None:
    value = payload.get("country_code", payload.get("country"))
    if value is None or value == "":
        return None
    value = str(value).strip().upper()
    if len(value) != 2 or not value.isalpha():
        raise ValueError("country_code must be a 2-letter code")
    return value


def _optional_float(payload: dict[str, Any], name: str) -> float | None:
    value = payload.get(name)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc


def _coordinates(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    latitude = _optional_float(payload, "latitude")
    longitude = _optional_float(payload, "longitude")
    if latitude is not None and not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if longitude is not None and not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    return latitude, longitude


def _status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status", "active")).strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError("invalid infrastructure status")
    return status


def list_regions_for_user(
    user: dict[str, Any] | None,
    backend,
    *,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """Return Regions visible to infrastructure administrators/controllers."""
    _require_reader(user)
    return InfrastructureRepository(backend).regions(active_only=active_only)


def upsert_region_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create or edit one Region.

    ``status=disabled`` is the supported administrative deactivation path.
    Physical deletion is intentionally excluded because Region rows may own
    Datacenters and placement history.
    """
    _require_admin(user)
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    region_id = _required_text(payload, "id")
    name = _required_text(payload, "name")
    country_code = _country_code(payload)
    continent_code = _optional_text(payload, "continent_code")
    if continent_code is not None:
        continent_code = continent_code.upper()
    latitude, longitude = _coordinates(payload)
    status = _status(payload)

    repository = LocationRepository(backend)
    repository.initialize()
    repository.upsert_region(
        region_id=region_id,
        name=name,
        country_code=country_code,
        continent_code=continent_code,
        latitude=latitude,
        longitude=longitude,
        status=status,
    )

    region = next(
        item
        for item in InfrastructureRepository(backend).regions()
        if str(item["id"]) == region_id
    )
    return region


def list_datacenters_for_user(
    user: dict[str, Any] | None,
    backend,
    *,
    region_id: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """Return Datacenters, optionally filtered by Region."""
    _require_reader(user)
    return InfrastructureRepository(backend).datacenters(
        region_id=region_id,
        active_only=active_only,
    )


def upsert_datacenter_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create or edit one Datacenter under an existing Region."""
    _require_admin(user)
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    datacenter_id = _required_text(payload, "id")
    region_id = _required_text(payload, "region_id")
    name = _required_text(payload, "name")
    status = _status(payload)
    provider = _optional_text(payload, "provider")
    city = _optional_text(payload, "city")
    country_code = _country_code(payload)
    latitude, longitude = _coordinates(payload)

    regions = InfrastructureRepository(backend).regions()
    if not any(str(region["id"]) == region_id for region in regions):
        raise ValueError("region not found")

    repository = LocationRepository(backend)
    repository.initialize()
    repository.upsert_datacenter(
        datacenter_id=datacenter_id,
        region_id=region_id,
        name=name,
        provider=provider,
        city=city,
        country_code=country_code,
        latitude=latitude,
        longitude=longitude,
        status=status,
    )

    datacenter = next(
        item
        for item in InfrastructureRepository(backend).datacenters()
        if str(item["id"]) == datacenter_id
    )
    return datacenter
