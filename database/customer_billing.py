#!/usr/bin/env python3
"""Canonical Customer billing identity rules for Database Baseline v2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_VALID_BILLING_STATUSES = {
    "pending",
    "active",
    "past_due",
    "suspended",
    "cancelled",
    "unlinked",
}


@dataclass(frozen=True)
class BillingIdentity:
    provider: str | None
    customer_id: str | None
    status: str | None

    @property
    def linked(self) -> bool:
        return self.provider is not None and self.customer_id is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "customer_id": self.customer_id,
            "status": self.status,
            "linked": self.linked,
        }


def normalize_billing_provider(value: Any) -> str | None:
    provider = str(value or "").strip().lower()
    if not provider:
        return None
    if not _PROVIDER_RE.fullmatch(provider):
        raise ValueError("invalid billing provider")
    return provider


def normalize_billing_customer_id(value: Any) -> str | None:
    customer_id = str(value or "").strip()
    if not customer_id:
        return None
    if len(customer_id) > 255 or any(ord(char) < 32 for char in customer_id):
        raise ValueError("invalid billing customer id")
    return customer_id


def normalize_billing_status(value: Any, *, linked: bool) -> str | None:
    status = str(value or "").strip().lower()
    if not status:
        return "active" if linked else None
    if status not in _VALID_BILLING_STATUSES:
        raise ValueError("invalid billing status")
    if not linked and status not in {"unlinked", "cancelled"}:
        raise ValueError("billing status requires a linked billing identity")
    return status


def normalize_billing_identity(
    *,
    provider: Any = None,
    customer_id: Any = None,
    status: Any = None,
) -> BillingIdentity:
    """Return a validated external billing reference.

    Provider and external customer id are an atomic pair.  A Customer may exist
    without billing, but a partial external billing identity is invalid.
    """

    normalized_provider = normalize_billing_provider(provider)
    normalized_customer_id = normalize_billing_customer_id(customer_id)
    if (normalized_provider is None) != (normalized_customer_id is None):
        raise ValueError("billing provider and customer id must be supplied together")
    linked = normalized_provider is not None
    normalized_status = normalize_billing_status(status, linked=linked)
    return BillingIdentity(
        provider=normalized_provider,
        customer_id=normalized_customer_id,
        status=normalized_status,
    )


def billing_unique_key(identity: BillingIdentity) -> tuple[str, str] | None:
    if not identity.linked:
        return None
    assert identity.provider is not None
    assert identity.customer_id is not None
    return identity.provider, identity.customer_id


__all__ = [
    "BillingIdentity",
    "billing_unique_key",
    "normalize_billing_customer_id",
    "normalize_billing_identity",
    "normalize_billing_provider",
    "normalize_billing_status",
]
