#!/usr/bin/env python3
"""Safe normalization for Agent metadata returned by different DB drivers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def decode_agent_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray, memoryview)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            return {}
    if raw is None:
        return {}
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = ["decode_agent_metadata"]
