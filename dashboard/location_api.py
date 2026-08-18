"""RBAC-aware location and placement API helpers."""

from __future__ import annotations

from typing import Any

from location_repository import LocationRepository


def _repository(backend):
    repository = LocationRepository(backend)
    repository.initialize()
    return repository


def regions_for_user(user, backend):
    if not user:
        raise PermissionError("authentication required")

    return _repository(backend).regions()


def datacenters_for_user(
    user,
    backend,
    region_id=None,
):
    if not user:
        raise PermissionError("authentication required")

    return _repository(backend).datacenters(
        str(region_id).strip() if region_id else None
    )


def placement_candidates_for_user(
    user: dict[str, Any] | None,
    backend,
    controller_id: str,
    region_id: str | None = None,
):
    if not user:
        raise PermissionError("authentication required")

    role = str(user.get("role", "")).lower()

    if role == "admin":
        pass
    elif role == "controller":
        if user.get("scope_id") != controller_id:
            raise PermissionError(
                "controller is outside user scope"
            )
    else:
        raise PermissionError(
            "placement inventory is not permitted"
        )

    return _repository(backend).candidates(
        controller_id,
        region_id=region_id,
    )
