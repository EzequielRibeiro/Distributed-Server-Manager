#!/usr/bin/env python3
"""JSON normalization helpers shared by Dashboard HTTP composition layers."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def normalize_json_value(value: Any) -> Any:
    """Return a JSON-safe copy of values commonly returned by DB backends.

    PostgreSQL drivers return DATE/TIMESTAMP and numeric columns as native
    Python objects, while SQLite frequently returns strings or floats.
    Normalizing at the HTTP boundary keeps the public API backend-independent
    without mutating repository data.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_json_value(item) for item in value]
    return value


def to_json_compatible(value: Any) -> Any:
    """Normalize Dashboard payloads into values accepted by ``json.dumps``.

    This explicit public name is used by HTTP composition layers that may
    receive database-native values from either PostgreSQL or SQLite.
    """
    return normalize_json_value(value)
