#!/usr/bin/env python3
"""Credential-only authentication boundary for Controller browser login."""

from __future__ import annotations

from typing import Any, Callable


Authenticator = Callable[[Any], dict | None]


def authenticate_login_credentials(
    headers: Any,
    *,
    controller_authenticator: Authenticator,
) -> dict | None:
    """Authenticate only a Controller/system identity supplied to this login.

    Browser sessions are intentionally excluded from a new login attempt: the
    current request must prove fresh credentials. Customer identities are also
    excluded from the administrative login boundary; Customers authenticate
    through the dedicated Customer session endpoint instead.
    """
    user = controller_authenticator(headers)
    if user is None:
        return None
    if user.get("role") not in {"admin", "controller", "operator"}:
        return None
    return user


__all__ = ["authenticate_login_credentials"]
