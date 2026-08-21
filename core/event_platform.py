#!/usr/bin/env python3
"""Canonical event envelope for the Capivara Universal Event Platform."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

EVENT_SCHEMA_VERSION = 1
EVENT_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
SEVERITIES = frozenset({"debug", "info", "warning", "error", "critical"})
LEGACY_EVENT_NAMESPACE = uuid.UUID("f24888b7-652e-4511-a4fa-32065a32e217")


class EventValidationError(ValueError):
    """Raised when a producer submits an invalid event envelope."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise EventValidationError(f"{field} is required")
    return text


def _timestamp(value: Any, field: str) -> str:
    text = _required_text(value, field)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventValidationError(f"{field} must be ISO-8601") from exc
    return text


def normalize_event(
    raw: Mapping[str, Any],
    *,
    default_source: str | None = None,
    default_source_id: str | None = None,
) -> dict[str, Any]:
    """Normalize producer-specific input into the stable C1 event envelope."""
    if not isinstance(raw, Mapping):
        raise EventValidationError("event must be an object")

    event_type = _required_text(raw.get("event_type"), "event_type").upper()
    if not EVENT_TYPE_RE.fullmatch(event_type):
        raise EventValidationError("event_type must use canonical UPPER_SNAKE_CASE")

    severity = str(raw.get("severity") or "info").strip().lower()
    if severity not in SEVERITIES:
        raise EventValidationError(f"unsupported severity: {severity}")

    data = raw.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise EventValidationError("data must be an object")

    event_id = _optional_text(raw.get("event_id")) or str(uuid.uuid4())
    source = _optional_text(raw.get("source")) or _optional_text(default_source)
    if source is None:
        raise EventValidationError("source is required")

    occurred_at = _timestamp(raw.get("occurred_at") or utc_now(), "occurred_at")
    schema_version = int(raw.get("schema_version") or EVENT_SCHEMA_VERSION)
    if schema_version != EVENT_SCHEMA_VERSION:
        raise EventValidationError(f"unsupported event schema version: {schema_version}")

    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "kind": "CapivaraUniversalEvent",
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "source": source,
        "source_id": _optional_text(raw.get("source_id")) or _optional_text(default_source_id),
        "severity": severity,
        "agent_id": _optional_text(raw.get("agent_id")),
        "instance_id": _optional_text(raw.get("instance_id")),
        "correlation_id": _optional_text(raw.get("correlation_id")),
        "causation_id": _optional_text(raw.get("causation_id")),
        "actor_type": _optional_text(raw.get("actor_type")),
        "actor_id": _optional_text(raw.get("actor_id")),
        "data": dict(data),
    }


def runtime_event_to_universal(raw: Mapping[str, Any], *, authenticated_agent_id: str) -> dict[str, Any]:
    """Translate both B11 legacy and C1 Agent runtime journal records."""
    agent_id = _required_text(raw.get("agent_id"), "agent_id")
    if agent_id != authenticated_agent_id:
        raise EventValidationError("runtime event Agent identity mismatch")
    translated = dict(raw)
    translated["event_type"] = raw.get("event_type") or raw.get("type")
    translated["source"] = "agent.runtime"
    translated["source_id"] = authenticated_agent_id
    translated["agent_id"] = authenticated_agent_id
    translated["schema_version"] = EVENT_SCHEMA_VERSION
    if not _optional_text(translated.get("event_id")):
        stable_payload = {
            "agent_id": authenticated_agent_id,
            "instance_id": raw.get("instance_id"),
            "event_type": translated.get("event_type"),
            "occurred_at": raw.get("occurred_at"),
            "data": raw.get("data") or {},
        }
        translated["event_id"] = str(uuid.uuid5(
            LEGACY_EVENT_NAMESPACE,
            json.dumps(stable_payload, sort_keys=True, separators=(",", ":"), default=str),
        ))
    return normalize_event(translated)
