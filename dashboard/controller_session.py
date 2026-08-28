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


SESSION_COOKIE = "capivara_session"
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
                    continue
                if expires_at > now:
                    _sessions[key] = dict(session)
        _loaded = True


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


def _cookie_secure() -> bool:
    explicit = os.environ.get("DSM_SESSION_COOKIE_SECURE")
    if explicit is not None:
        return explicit.strip().lower() not in {"0", "false", "no", "off"}
    return os.environ.get("DSM_WEB_SCHEME", "http").strip().lower() == "https"


def create_session(user: dict) -> str:
    _load_sessions()
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
        _sessions[_token_key(token)] = session
        _persist_sessions()
    return token


def get_session(token: str | None) -> dict | None:
    if not token:
        return None
    _load_sessions()
    now = int(time.time())
    key = _token_key(token)
    with _lock:
        session = _sessions.get(key)
        if session is None:
            return None
        if int(session.get("expires_at", 0)) <= now:
            _sessions.pop(key, None)
            _persist_sessions()
            return None
        return dict(session)


def revoke_session(token: str | None) -> None:
    if not token:
        return
    _load_sessions()
    with _lock:
        if _sessions.pop(_token_key(token), None) is not None:
            _persist_sessions()


def revoke_user_sessions(username: str, *, role: str | None = None) -> int:
    """Revoke every browser session belonging to one identity."""
    _load_sessions()
    removed = 0
    with _lock:
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
    expires = formatdate(time.time() + SESSION_TTL, usegmt=True)
    flags = [
        f"{SESSION_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        f"Max-Age={SESSION_TTL}",
        f"Expires={expires}",
    ]
    if _cookie_secure():
        flags.append("Secure")
    return "; ".join(flags)


def expired_cookie_header() -> str:
    flags = [
        f"{SESSION_COOKIE}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        "Max-Age=0",
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
    ]
    if _cookie_secure():
        flags.append("Secure")
    return "; ".join(flags)
