#!/usr/bin/env python3
"""Canonical public Customer code helpers for Database Baseline v2."""

from __future__ import annotations

import re


CUSTOMER_CODE_PREFIX = "CLI-"
CUSTOMER_CODE_WIDTH = 6
# The public format is zero-padded (CLI-000001). Parse the digit payload first
# and then require an exact round trip through format_customer_code(). This also
# supports IDs wider than six digits without accepting non-canonical variants.
_CUSTOMER_CODE_RE = re.compile(r"^CLI-([0-9]+)$", re.IGNORECASE)


def format_customer_code(customer_id: int) -> str:
    """Return the immutable public code for a positive numeric Customer PK."""
    if isinstance(customer_id, bool):
        raise ValueError("customer id must be a positive integer")
    try:
        numeric_id = int(customer_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("customer id must be a positive integer") from exc
    if numeric_id <= 0:
        raise ValueError("customer id must be a positive integer")
    return f"{CUSTOMER_CODE_PREFIX}{numeric_id:0{CUSTOMER_CODE_WIDTH}d}"


def parse_customer_code(value: str) -> int:
    """Resolve one canonical public ``CLI-NNNNNN`` code to its Customer PK."""
    normalized = str(value or "").strip()
    match = _CUSTOMER_CODE_RE.fullmatch(normalized)
    if match is None:
        raise ValueError("invalid customer code")
    numeric_id = int(match.group(1))
    if numeric_id <= 0:
        raise ValueError("invalid customer code")
    canonical = format_customer_code(numeric_id)
    if normalized.upper() != canonical:
        raise ValueError("invalid customer code")
    return numeric_id


def is_customer_code(value: str) -> bool:
    try:
        parse_customer_code(value)
    except ValueError:
        return False
    return True


__all__ = [
    "CUSTOMER_CODE_PREFIX",
    "CUSTOMER_CODE_WIDTH",
    "format_customer_code",
    "parse_customer_code",
    "is_customer_code",
]
