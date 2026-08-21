from __future__ import annotations

import json
from typing import Any

from .models import UniversalEvent
from .registry import require_registered


class EventValidationError(ValueError):
    """Raised when a universal event violates the platform contract."""


def validate_event(event: UniversalEvent) -> UniversalEvent:
    if not isinstance(event, UniversalEvent):
        raise EventValidationError("event must be a UniversalEvent instance")

    try:
        require_registered(event.type)
    except ValueError as exc:
        raise EventValidationError(str(exc)) from exc

    if not event.id.startswith("evt_"):
        raise EventValidationError("event id must use the evt_ prefix")

    if event.timestamp.tzinfo is None:
        raise EventValidationError("event timestamp must be timezone-aware")

    if not event.source.type.strip() or not event.source.id.strip():
        raise EventValidationError("event source must be complete")

    if not isinstance(event.data, dict):
        raise EventValidationError("event data must be a dictionary")

    _require_json_serializable(event.to_dict())
    return event


def _require_json_serializable(value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise EventValidationError("event payload must be JSON serializable") from exc
