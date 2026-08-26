#!/usr/bin/env python3
"""Credential-only authentication boundary for browser login requests."""

from __future__ import annotations

from typing import Any, Callable


Authenticator = Callable[[Any], dict | None]


def authenticate_login_credentials(
    headers: Any,
    *,
    controller_authenticator: Authenticator,
    customer_authenticator: Authenticator,
) -> dict | None:
    """Authenticate only the Authorization header supplied to this login.

    Session-cookie authentication is intentionally excluded.  General browser
    requests may reuse an established session, but a new login must prove the
    credentials in the current request and must never inherit an old identity.
    """

    user = controller_authenticator(headers)

    # Legacy dashboard authentication can still recognize Customer users.
    # Never accept that reduced legacy identity here: Customer credentials
    # must be resolved by the canonical Customer authenticator.
    if user is not None and user.get("role") != "customer":
        return user

    try:
        return customer_authenticator(headers)
    except Exception:
        return None


__all__ = ["authenticate_login_credentials"]
