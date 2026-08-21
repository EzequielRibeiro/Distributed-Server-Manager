#!/usr/bin/env python3
"""HTTP adapter for Universal Observability."""

from __future__ import annotations

from urllib.parse import parse_qs

from observability_api import query_observability

OBSERVABILITY_PATH = "/api/observability"


def dispatch_observability_get(path: str, query: str, *, user, backend):
    if path != OBSERVABILITY_PATH:
        return 404, {"error": "not_found"}
    values = parse_qs(query or "")
    filters = {key: (value[0] if value else None) for key, value in values.items()}
    try:
        body = query_observability(user=user, backend=backend, filters=filters)
        return 200, body
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}


__all__ = ["OBSERVABILITY_PATH", "dispatch_observability_get"]
