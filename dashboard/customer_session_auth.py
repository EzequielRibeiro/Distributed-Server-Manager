#!/usr/bin/env python3
"""Session-aware authentication bridge for Customer browser requests."""

from __future__ import annotations

from typing import Any, Callable


def authenticate_browser_customer(
    headers,
    *,
    session_authenticator: Callable[[Any], dict | None],
    fallback_authenticator: Callable[[Any], dict | None],
) -> dict | None:
    """Prefer the established browser session, then legacy/header auth.

    Browser subresource requests such as ``<script src=...>`` carry the
    Capivara session cookie but do not automatically repeat the Authorization
    header used during login.  This bridge keeps both authentication contracts
    compatible while making the cookie-backed browser session authoritative.
    """
    user = session_authenticator(headers)
    if user is not None:
        return user
    return fallback_authenticator(headers)


__all__ = ["authenticate_browser_customer"]
