#!/usr/bin/env python3
"""HTTP-safe read API for the Universal Event Platform timeline."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from event_repository import EventRepository
from core.events.timeline import TimelineConsumer
from core.events.registry import is_registered

TIMELINE_PATH = "/api/events/timeline"
MAX_TIMELINE_LIMIT = 200
DEFAULT_TIMELINE_LIMIT = 100


def _single(query: dict[str, list[str]], name: str) -> str | None:
    value = (query.get(name) or [None])[0]
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _limit(value: str | None) -> int:
    if value is None:
        return DEFAULT_TIMELINE_LIMIT
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if parsed < 1 or parsed > MAX_TIMELINE_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_TIMELINE_LIMIT}")
    return parsed


def _scoped_filters(
    user: dict[str, Any] | None,
    query: dict[str, list[str]],
) -> dict[str, Any]:
    if not user:
        raise PermissionError("authentication required")

    role = str(user.get("role", "")).strip().lower()
    scope_id = str(user.get("scope_id", "")).strip()

    filters: dict[str, Any] = {
        "controller_id": _single(query, "controller_id"),
        "agent_id": _single(query, "agent_id"),
        "customer_id": _single(query, "customer_id"),
        "instance_id": _single(query, "instance_id"),
        "correlation_id": _single(query, "correlation_id"),
        "event_type": _single(query, "event_type"),
        "limit": _limit(_single(query, "limit")),
        "newest_first": (_single(query, "order") or "desc").lower() != "asc",
    }

    if filters["event_type"] and not is_registered(str(filters["event_type"])):
        raise ValueError("unknown event_type")

    if role == "admin":
        return filters

    if role == "controller":
        if not scope_id:
            raise PermissionError("controller scope is required")
        requested = filters["controller_id"]
        if requested and requested != scope_id:
            raise PermissionError("controller is outside user scope")
        filters["controller_id"] = scope_id
        return filters

    if role == "customer":
        if not scope_id:
            raise PermissionError("customer scope is required")
        requested = filters["customer_id"]
        if requested and requested != scope_id:
            raise PermissionError("customer is outside user scope")
        filters["customer_id"] = scope_id
        return filters

    raise PermissionError("timeline access is not permitted")


def dispatch_timeline_get(
    path: str,
    query_string: str,
    *,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    if path != TIMELINE_PATH:
        return None

    try:
        query = parse_qs(query_string, keep_blank_values=True)
        filters = _scoped_filters(user, query)
        entries = TimelineConsumer(EventRepository(backend)).entries(**filters)
        return 200, {
            "items": [entry.to_dict() for entry in entries],
            "count": len(entries),
            "order": "desc" if filters["newest_first"] else "asc",
        }
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {
            "error": "timeline_read_failed",
            "message": "Não foi possível consultar a linha do tempo.",
        }


__all__ = [
    "TIMELINE_PATH",
    "MAX_TIMELINE_LIMIT",
    "DEFAULT_TIMELINE_LIMIT",
    "dispatch_timeline_get",
]
