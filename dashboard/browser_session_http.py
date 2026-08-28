#!/usr/bin/env python3
"""Canonical browser-session HTTP boundary for Controller and Customer portals."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from controller_session import (
    cookie_header,
    create_session,
    expired_cookie_header,
    revoke_session,
    session_token_from_headers,
    session_user_from_headers,
)
from customer_http_auth import authenticate_customer
from customer_security import customer_rate_limiter, remote_identity

ADMIN_LOGIN_PATH = "/api/auth/login"
CUSTOMER_LOGIN_PATH = "/api/customer/auth/session"
LOGOUT_PATH = "/api/auth/logout"
SESSION_PATH = "/api/auth/session"
BRIDGE_PATH = "/browser-session-bridge.js"
BRIDGE_TAG = '<script src="/browser-session-bridge.js?v=1"></script>'


def _body(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _send(handler, status: int, payload: dict, *, cookie: str | None = None) -> None:
    body = _body(payload)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    if cookie is not None:
        handler.send_header("Set-Cookie", cookie)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _replace_session(handler, user: dict) -> str:
    revoke_session(session_token_from_headers(handler.headers))
    return create_session(user)


def _login_allowed(handler, bucket: str, *, limit: int = 10, window: int = 300) -> bool:
    key = remote_identity(handler)
    decision = customer_rate_limiter.check(bucket, key, limit=limit, window_seconds=window)
    if decision.allowed:
        return True
    body = _body({"error": "too_many_requests"})
    handler.send_response(429)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Retry-After", str(decision.retry_after))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return False


def _serve_html_with_bridge(handler, path: Path) -> bool:
    if path.suffix.lower() != ".html":
        return False
    if session_user_from_headers(handler.headers) is None:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if BRIDGE_TAG not in text:
        if "</head>" in text:
            text = text.replace("</head>", f"{BRIDGE_TAG}</head>", 1)
        elif "</body>" in text:
            text = text.replace("</body>", f"{BRIDGE_TAG}</body>", 1)
        else:
            text = BRIDGE_TAG + text
    body = text.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "text/html; charset=utf-8")
    # The existing Dashboard still uses inline *style attributes* for dynamic
    # widths/visibility in several legacy widgets. Keep script execution locked
    # to same-origin while allowing those styles until that frontend debt is
    # removed. Do not enable unsafe-inline for scripts.
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


def install_browser_session_http(legacy, controller_credential_authenticator) -> None:
    """Install the final web-session boundary after all legacy HTTP wrappers."""
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST
    previous_send_file = legacy.DashboardHandler.send_file
    legacy.STATIC_FILES[BRIDGE_PATH] = legacy.WEB_DIR / "browser-session-bridge.js"

    def session_aware_send_file(self, path):
        candidate = Path(path)
        if _serve_html_with_bridge(self, candidate):
            return
        return previous_send_file(self, path)

    def browser_session_get(self):
        path = urlparse(self.path).path
        if path != SESSION_PATH:
            return previous_get(self)
        user = session_user_from_headers(self.headers)
        if user is None:
            _send(self, 401, {"authenticated": False})
            return
        _send(
            self,
            200,
            {
                "authenticated": True,
                "username": user.get("username", ""),
                "role": user.get("role", ""),
                "scope_id": user.get("scope_id", ""),
            },
        )

    def browser_session_post(self):
        path = urlparse(self.path).path
        if path == ADMIN_LOGIN_PATH:
            if not _login_allowed(self, "controller-browser-login"):
                return
            user = controller_credential_authenticator(self.headers)
            if user is None or user.get("role") not in {"admin", "controller", "operator"}:
                revoke_session(session_token_from_headers(self.headers))
                _send(
                    self,
                    401,
                    {"error": "invalid_credentials", "message": "Usuário ou senha inválidos."},
                    cookie=expired_cookie_header(),
                )
                return
            token = _replace_session(self, user)
            _send(
                self,
                200,
                {"authenticated": True, "role": user.get("role"), "username": user.get("username")},
                cookie=cookie_header(token),
            )
            return

        if path == CUSTOMER_LOGIN_PATH:
            if not _login_allowed(self, "customer-browser-login"):
                return
            try:
                backend = legacy.dashboard_repository(legacy.DATABASE_FILE).backend
                user = authenticate_customer(self.headers, backend)
            except Exception:
                user = None
            if user is None or user.get("role") != "customer":
                revoke_session(session_token_from_headers(self.headers))
                _send(
                    self,
                    401,
                    {"error": "invalid_credentials", "message": "Usuário ou senha inválidos."},
                    cookie=expired_cookie_header(),
                )
                return
            token = _replace_session(self, user)
            _send(
                self,
                200,
                {"authenticated": True, "role": "customer", "username": user.get("username")},
                cookie=cookie_header(token),
            )
            return

        if path == LOGOUT_PATH:
            revoke_session(session_token_from_headers(self.headers))
            _send(
                self,
                200,
                {"authenticated": False},
                cookie=expired_cookie_header(),
            )
            return

        return previous_post(self)

    legacy.DashboardHandler.send_file = session_aware_send_file
    legacy.DashboardHandler.do_GET = browser_session_get
    legacy.DashboardHandler.do_POST = browser_session_post


__all__ = [
    "ADMIN_LOGIN_PATH",
    "BRIDGE_PATH",
    "CUSTOMER_LOGIN_PATH",
    "LOGOUT_PATH",
    "SESSION_PATH",
    "install_browser_session_http",
]
