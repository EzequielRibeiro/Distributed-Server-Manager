#!/usr/bin/env python3
"""HTTP-facing dispatcher for Dashboard infrastructure topology and Doctor.

This module deliberately contains no BaseHTTPRequestHandler dependency. The
Dashboard server delegates matching infrastructure requests here with a
minimal adapter, while authorization and response composition remain outside
server.py.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from infrastructure_api import infrastructure_for_user
from infrastructure_doctor_http import dispatch_infrastructure_doctor_get


INFRASTRUCTURE_PATH = "/api/infrastructure"


def _single_query_value(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name, [])
    if not values:
        return None
    value = str(values[0]).strip()
    return value or None


def dispatch_infrastructure_get(
    path: str,
    query_string: str,
    *,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    """Handle infrastructure GET endpoints or return None for another path.

    The return value is intentionally transport-neutral: ``(status, body)``.
    This lets server.py keep ownership of JSON serialization and HTTP headers.
    """
    doctor_result = dispatch_infrastructure_doctor_get(
        path,
        user=user,
        backend=backend,
    )
    if doctor_result is not None:
        return doctor_result

    if path != INFRASTRUCTURE_PATH:
        return None

    query = parse_qs(query_string, keep_blank_values=True)
    controller_id = _single_query_value(query, "controller_id")
    active_value = (_single_query_value(query, "active_only") or "").lower()
    active_only = active_value in {"1", "true", "yes", "on"}

    try:
        payload = infrastructure_for_user(
            user,
            backend,
            controller_id=controller_id,
            active_only=active_only,
        )
        return 200, payload
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except ValueError as exc:
        return 404, {"error": str(exc)}
    except Exception:
        return 500, {"error": "failed to load infrastructure topology"}
