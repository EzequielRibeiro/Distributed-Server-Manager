"""Region preference helpers for Dashboard clients."""

from __future__ import annotations

from typing import Any

from core.placement.region_preference import (
    region_preference_from_payload,
)


def region_options_for_user(
    user: dict[str, Any] | None,
    backend,
):
    if not user:
        raise PermissionError("authentication required")

    from location_repository import LocationRepository

    repository = LocationRepository(backend)
    repository.initialize()

    return {
        "regions": repository.regions(),
        "selection_mode": "preference",
    }


def region_preference_for_creation(
    user: dict[str, Any] | None,
    payload: dict[str, Any] | None,
):
    if not user:
        raise PermissionError("authentication required")

    if str(user.get("role", "")).lower() != "customer":
        raise PermissionError(
            "region preference is available to customers"
        )

    preference = region_preference_from_payload(payload)

    return {
        "region_id": preference.region_id,
        "allow_cross_region": preference.allow_cross_region,
    }
