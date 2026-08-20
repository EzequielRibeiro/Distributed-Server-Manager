#!/usr/bin/env python3
"""HTTP dispatcher contract for the modern infrastructure Doctor."""

from __future__ import annotations

from typing import Any

from infrastructure_doctor_api import infrastructure_doctor_for_user

INFRASTRUCTURE_DOCTOR_PATH = "/api/infrastructure/doctor"


def dispatch_infrastructure_doctor_get(
    path: str,
    *,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    """Handle the modern Doctor GET endpoint without HTTP-server coupling."""
    if path != INFRASTRUCTURE_DOCTOR_PATH:
        return None
    if not user:
        return 401, {"error": "authentication required"}
    try:
        return 200, infrastructure_doctor_for_user(user, backend)
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except Exception:
        return 500, {"error": "failed to run infrastructure Doctor"}


__all__ = [
    "INFRASTRUCTURE_DOCTOR_PATH",
    "dispatch_infrastructure_doctor_get",
]
