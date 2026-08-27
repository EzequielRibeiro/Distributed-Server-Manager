#!/usr/bin/env python3
"""HTTP adapter for P8 administrative observability."""

from __future__ import annotations

from urllib.parse import parse_qs

from admin_observability_api import consolidated_observability

ADMIN_OBSERVABILITY_PATH = "/api/admin/observability"


def dispatch_admin_observability_get(path: str, query: str, *, user, backend):
    if path != ADMIN_OBSERVABILITY_PATH:
        return 404, {"error": "not_found"}
    values = parse_qs(query or "")
    filters = {key: (value[0] if value else None) for key, value in values.items()}
    try:
        return 200, consolidated_observability(user=user, backend=backend, filters=filters)
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}


__all__ = ["ADMIN_OBSERVABILITY_PATH", "dispatch_admin_observability_get"]
