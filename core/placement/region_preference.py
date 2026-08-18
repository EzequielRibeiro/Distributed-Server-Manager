"""Customer region preference model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RegionPreference:
    region_id: str | None = None
    allow_cross_region: bool = False


def region_preference_from_payload(
    payload: dict[str, Any] | None,
) -> RegionPreference:
    payload = payload or {}

    raw_region = payload.get("region_id")

    region_id = (
        str(raw_region).strip()
        if raw_region is not None
        else None
    )

    if region_id == "":
        region_id = None

    allow_cross_region = bool(
        payload.get("allow_cross_region", False)
    )

    return RegionPreference(
        region_id=region_id,
        allow_cross_region=allow_cross_region,
    )
