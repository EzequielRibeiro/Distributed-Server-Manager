#!/usr/bin/env python3
"""HTTP session management for the Capivara DSM Controller."""

from __future__ import annotations

import secrets
import threading
import time


SESSION_COOKIE = "capivara_session"
SESSION_TTL = 8 * 60 * 60

_sessions: dict[str, dict] = {}
_lock = threading.RLock()


def create_session(user: dict) -> str:
    token = secrets.token_urlsafe(48)

    now = int(time.time())

    session = {
        "username": user["username"],
        "role": user["role"],
        "scope_id": user.get("scope_id", ""),
        "created_at": now,
        "expires_at": now + SESSION_TTL,
    }

    with _lock:
        _sessions[token] = session

    return token


def get_session(token: str | None) -> dict | None:
    if not token:
        return None

    now = int(time.time())

    with _lock:
        session = _sessions.get(token)

        if session is None:
            return None

        if session["expires_at"] <= now:
            _sessions.pop(token, None)
            return None

        return dict(session)


def revoke_session(token: str | None) -> None:
    if not token:
        return

    with _lock:
        _sessions.pop(token, None)


def session_token_from_headers(headers) -> str | None:
    raw = headers.get("Cookie", "")

    for item in raw.split(";"):
        name, separator, value = item.strip().partition("=")

        if separator and name == SESSION_COOKIE:
            return value or None

    return None


def session_user_from_headers(headers) -> dict | None:
    token = session_token_from_headers(headers)
    session = get_session(token)

    if session is None:
        return None

    return {
        "username": session["username"],
        "role": session["role"],
        "scope_id": session.get("scope_id", ""),
    }


def cookie_header(token: str) -> str:
    return (
        f"{SESSION_COOKIE}={token}; "
        f"Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
    )


def expired_cookie_header() -> str:
    return (
        f"{SESSION_COOKIE}=; "
        "Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
    )
