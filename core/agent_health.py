#!/usr/bin/env python3
"""Pure heartbeat health rules for Capivara Agents."""

from __future__ import annotations

from datetime import datetime, timezone

HEALTH_STATES = frozenset({"online", "degraded", "offline"})


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    result = datetime.fromisoformat(text)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def utc_timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def derive_agent_health(
    last_seen: str | None,
    *,
    now: datetime | None = None,
    degraded_after_seconds: int = 60,
    offline_after_seconds: int = 120,
) -> str:
    """Derive operational health without changing administrative status."""
    if degraded_after_seconds < 1:
        raise ValueError("degraded_after_seconds must be positive")
    if offline_after_seconds <= degraded_after_seconds:
        raise ValueError("offline_after_seconds must exceed degraded_after_seconds")

    seen = parse_timestamp(last_seen)
    if seen is None:
        return "offline"

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = max(0.0, (current.astimezone(timezone.utc) - seen).total_seconds())

    if age >= offline_after_seconds:
        return "offline"
    if age >= degraded_after_seconds:
        return "degraded"
    return "online"
