#!/usr/bin/env python3
"""HTTP dispatcher for Agent geographic location administration."""

from __future__ import annotations

from typing import Any

from agent_location_safety import safely_set_agent_location_for_user

AGENT_LOCATION_PATH = "/api/agent/location"


def dispatch_agent_location_post(
    path: str,
    payload: dict[str, Any] | None,
    *,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    if path != AGENT_LOCATION_PATH:
        return None
    try:
        result = safely_set_agent_location_for_user(user, backend, payload)
        return 200, result
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except Exception:
        return 500, {"error": "failed to update agent location safely"}
