#!/usr/bin/env python3
"""Persistent HTTP session management for the Capivara DSM Controller."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
from email.utils import formatdate


CONTROLLER_SESSION_COOKIE = "capivara_controller_session"
CUSTOMER_SESSION_COOKIE = "capivara_customer_session"

# Compatibility name. New code must select an explicit area.
SESSION_COOKIE = CONTROLLER_SESSION_COOKIE
SESSION_TTL = int(os.environ.get("DSM_BROWSER_SESSION_TTL_SECONDS", str(8 * 60 * 60)))
SESSION_FILE = Path(
    os.environ.get(
        "DSM_BROWSER_SESSION_FILE",
        str(Path(os.environ.get("DSM_ROOT", "/opt/dsm")) / "runtime" / "browser-sessions.json"),
    )
)

_sessions: dict[str, dict] = {}
_lock = threading.RLock()
_loaded = False


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_sessions() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        now = int(time.time())
        expired_found = False
        try:
            raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            for key, session in raw.items():
                if not isinstance(key, str) or not isinstance(session, dict):
                    continue
                try:
                    expires_at = int(session.get("expires_at", 0))
                except (TypeError, ValueError):
                    expires_at = 0
                if expires_at > now:
                    _sessions[key] = dict(session)
                else:
                    expired_found = True
        _loaded = True
        if expired_found:
            _persist_sessions()


def _persist_sessions() -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SESSION_FILE.with_name(f".{SESSION_FILE.name}.{os.getpid()}.tmp")
    payload = json.dumps(_sessions, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, SESSION_FILE)
    try:
        os.chmod(SESSION_FILE, 0o600)
    except OSError:
        pass


def _prune_expired_sessions_locked(now: int | None = None) -> int:
    current = int(time.time()) if now is None else int(now)
    removed = 0
    for key, session in list(_sessions.items()):
        try:
            expires_at = int(session.get("expires_at", 0))
        except (TypeError, ValueError):
            expires_at = 0
        if expires_at > current:
            continue
        _sessions.pop(key, None)
        removed += 1
    if removed:
        _persist_sessions()
    return removed


def _cookie_secure() -> bool:
    explicit = os.environ.get("DSM_SESSION_COOKIE_SECURE")
    if explicit is not None:
        return explicit.strip().lower() not in {"0", "false", "no", "off"}
    return os.environ.get("DSM_WEB_SCHEME", "http").strip().lower() == "https"


def create_session(user: dict, *, area: str | None = None) -> str:
    _load_sessions()
    token = secrets.token_urlsafe(48)
    now = int(time.time())

    role = str(user.get("role") or "").strip().lower()

    # Preserve compatibility with existing internal callers while making every
    # newly-created browser session carry an explicit authentication domain.
    if area is None:
        normalized_area = "customer" if role == "customer" else "controller"
    else:
        normalized_area = str(area or "").strip().lower()

    if normalized_area not in {"controller", "customer"}:
        raise ValueError(f"invalid session area: {area}")

    if normalized_area == "controller":
        if role not in {"admin", "controller", "operator"}:
            raise ValueError("controller session requires a Controller role")
    elif role != "customer":
        raise ValueError("customer session requires the Customer role")

    session = {
        "username": user["username"],
        "role": user["role"],
        "scope_id": user.get("scope_id", ""),
        "area": normalized_area,
        "created_at": now,
        "expires_at": now + SESSION_TTL,
    }

    # Customer sessions must preserve the canonical Customer identity.
    # Never persist password hashes, Basic credentials, or other secrets.
    if user.get("customer_id") is not None:
        session["customer_id"] = user["customer_id"]

    if user.get("customer_code"):
        session["customer_code"] = user["customer_code"]

    with _lock:
        _prune_expired_sessions_locked(now)
        _sessions[_token_key(token)] = session
        _persist_sessions()

    return token


def get_session(token: str | None) -> dict | None:
    _load_sessions()
    now = int(time.time())
    with _lock:
        _prune_expired_sessions_locked(now)
        if not token:
            return None
        session = _sessions.get(_token_key(token))
        if session is None:
            return None
        return dict(session)


def revoke_session(token: str | None) -> None:
    _load_sessions()
    with _lock:
        _prune_expired_sessions_locked()
        if not token:
            return
        if _sessions.pop(_token_key(token), None) is not None:
            _persist_sessions()


def revoke_user_sessions(username: str, *, role: str | None = None) -> int:
    """Revoke every browser session belonging to one identity."""
    _load_sessions()
    removed = 0
    with _lock:
        _prune_expired_sessions_locked()
        for key, session in list(_sessions.items()):
            if session.get("username") != username:
                continue
            if role is not None and session.get("role") != role:
                continue
            _sessions.pop(key, None)
            removed += 1
        if removed:
            _persist_sessions()
    return removed


def _cookie_name(area: str = "controller") -> str:
    normalized = str(area or "controller").strip().lower()
    if normalized == "customer":
        return CUSTOMER_SESSION_COOKIE
    if normalized == "controller":
        return CONTROLLER_SESSION_COOKIE
    raise ValueError(f"invalid session area: {area}")


def session_token_from_headers(headers, *, area: str = "controller") -> str | None:
    cookie_name = _cookie_name(area)
    raw = headers.get("Cookie", "")
    for item in raw.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == cookie_name:
            return value or None
    return None


def session_user_from_headers(headers, *, area: str = "controller") -> dict | None:
    token = session_token_from_headers(headers, area=area)
    session = get_session(token)

    if session is None:
        return None

    normalized_area = str(area or "controller").strip().lower()
    if normalized_area not in {"controller", "customer"}:
        return None

    role = str(session.get("role") or "").strip().lower()
    session_area = str(session.get("area") or "").strip().lower()

    # New sessions are bound cryptographically to a stored authentication
    # domain. Older persisted sessions did not contain "area", so their role is
    # used as a fail-closed compatibility boundary.
    if session_area:
        if session_area != normalized_area:
            return None
    elif normalized_area == "customer":
        if role != "customer":
            return None
    elif role not in {"admin", "controller", "operator"}:
        return None

    if normalized_area == "customer" and role != "customer":
        return None

    if normalized_area == "controller" and role not in {
        "admin",
        "controller",
        "operator",
    }:
        return None

    user = {
        "username": session["username"],
        "role": session["role"],
        "scope_id": session.get("scope_id", ""),
    }

    if session.get("customer_id") is not None:
        user["customer_id"] = session["customer_id"]

    if session.get("customer_code"):
        user["customer_code"] = session["customer_code"]

    return user


def cookie_header(token: str, *, area: str = "controller") -> str:
    expires = formatdate(time.time() + SESSION_TTL, usegmt=True)
    flags = [
        f"{_cookie_name(area)}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        f"Max-Age={SESSION_TTL}",
        f"Expires={expires}",
    ]
    if _cookie_secure():
        flags.append("Secure")
    return "; ".join(flags)


def expired_cookie_header(*, area: str = "controller") -> str:
    flags = [
        f"{_cookie_name(area)}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        "Max-Age=0",
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
    ]
    if _cookie_secure():
        flags.append("Secure")
    return "; ".join(flags)