#!/usr/bin/env python3
"""JSON normalization helpers shared by Dashboard HTTP composition layers."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def normalize_json_value(value: Any) -> Any:
    """Return a JSON-safe copy of values commonly returned by DB backends.

    PostgreSQL drivers return DATE/TIMESTAMP columns as native Python objects,
    while SQLite frequently returns strings. Normalizing at the HTTP boundary
    keeps the public API backend-independent without mutating repository data.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_json_value(item) for item in value]
    return value
