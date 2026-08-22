#!/usr/bin/env python3
"""JSON response normalization shared by every Dashboard API layer.

Database drivers do not return the same Python value types. PostgreSQL and
MySQL commonly return temporal columns as datetime/date/time objects while the
legacy SQLite paths frequently return strings. Normalize only transport-facing
values here so every API can keep its persistence-native types internally.
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID


def json_safe(value: Any) -> Any:
    """Recursively convert common non-JSON transport values.

    Unknown objects are intentionally left untouched so programming mistakes
    still fail loudly instead of being silently stringified.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    return value


def install_json_safe_responses(handler_class) -> None:
    """Wrap a Dashboard handler's existing ``send_json`` exactly once."""
    current = handler_class.send_json
    if getattr(current, "_capivara_json_safe", False):
        return

    def send_json(self, code, payload):
        return current(self, code, json_safe(payload))

    send_json._capivara_json_safe = True
    handler_class.send_json = send_json


__all__ = ["install_json_safe_responses", "json_safe"]
