#!/usr/bin/env python3
"""Customer reference resolution for Database Baseline v2.

External callers use the immutable public ``CLI-NNNNNN`` code. Persistence
relationships use the numeric ``customers.id`` primary key exclusively.
"""

from __future__ import annotations

from typing import Any

from customer_code import format_customer_code, parse_customer_code


def customer_pk(value: Any) -> int:
    """Normalize an internal numeric Customer primary key."""
    if isinstance(value, bool):
        raise ValueError("invalid customer id")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid customer id") from exc
    if result <= 0:
        raise ValueError("invalid customer id")
    return result


def customer_code_to_pk(value: str) -> int:
    """Resolve one canonical public Customer code without database access."""
    return parse_customer_code(value)


def resolve_customer_reference(value: Any, *, public_only: bool = False) -> int:
    """Resolve a Customer reference at a repository boundary.

    Public HTTP/API boundaries should set ``public_only=True``. Internal callers
    may pass an already-resolved positive numeric primary key.
    """
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.upper().startswith("CLI-"):
            return customer_code_to_pk(normalized)
        if public_only:
            raise ValueError("customer_code must use CLI-NNNNNN")
    if public_only:
        raise ValueError("customer_code must use CLI-NNNNNN")
    return customer_pk(value)


def public_reference(value: Any) -> dict[str, Any]:
    pk = customer_pk(value)
    return {"id": pk, "customer_code": format_customer_code(pk)}


__all__ = [
    "customer_pk",
    "customer_code_to_pk",
    "resolve_customer_reference",
    "public_reference",
]
