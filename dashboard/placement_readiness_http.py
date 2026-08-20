#!/usr/bin/env python3
"""Customer-safe placement readiness HTTP dispatcher."""

from __future__ import annotations

from typing import Any

from location_repository import LocationRepository

PLACEMENT_READINESS_PATH = "/api/placement/readiness"


def placement_readiness_for_customer(
    user: dict[str, Any] | None,
    backend,
) -> dict[str, Any]:
    if (
        not user
        or str(user.get("role", "")).strip().lower() != "customer"
        or not user.get("scope_id")
    ):
        raise PermissionError("customer authentication required")

    repository = LocationRepository(backend)
    repository.initialize()
    ph = repository.dialect.placeholder

    with repository.backend.connect() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT controller_id,status FROM customers WHERE id=" + ph,
                (str(user["scope_id"]),),
            )
            row = cursor.fetchone()
        finally:
            cursor.close()

    if row is None or str(row["status"]).strip().lower() != "active":
        raise PermissionError("customer is not active")

    controller_id = str(row["controller_id"]).strip()
    candidates = repository.candidates(controller_id)
    ready = bool(candidates)

    return {
        "placement_ready": ready,
        "state": "available" if ready else "unavailable",
    }


def dispatch_placement_readiness_get(
    path: str,
    *,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    if path != PLACEMENT_READINESS_PATH:
        return None

    try:
        return 200, placement_readiness_for_customer(user, backend)
    except PermissionError:
        return 403, {
            "error": "forbidden",
            "message": "Acesso não autorizado.",
        }
    except Exception:
        return 500, {
            "error": "readiness_unavailable",
            "message": "Não foi possível verificar a disponibilidade dos ambientes.",
        }


__all__ = [
    "PLACEMENT_READINESS_PATH",
    "dispatch_placement_readiness_get",
    "placement_readiness_for_customer",
]
