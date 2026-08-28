#!/usr/bin/env python3
"""Canonical browser-session HTTP boundary for Controller and Customer portals."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from controller_session import (
    cookie_header,
    create_session,
    expired_cookie_header,
    revoke_session,
    session_token_from_headers,
    session_user_from_headers,
)
from activity_audit_repository import ActivityAuditRepository
from customer_http_auth import authenticate_customer
from customer_security import customer_rate_limiter, remote_identity

ADMIN_LOGIN_PATH = "/api/auth/login"
CUSTOMER_LOGIN_PATH = "/api/customer/auth/session"
CUSTOMER_LOGOUT_PATH = "/api/customer/auth/logout"
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


def _replace_session(handler, user: dict, *, area: str) -> str:
    revoke_session(session_token_from_headers(handler.headers, area=area))
    return create_session(user, area=area)


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


def install_browser_session_http(legacy, controller_credential_authenticator) -> None:
    """Install the final web-session boundary after all legacy HTTP wrappers."""
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST
    legacy.STATIC_FILES[BRIDGE_PATH] = legacy.WEB_DIR / "browser-session-bridge.js"

    def audit_auth(handler, user: dict | None, action: str, *, area: str) -> None:
        if user is None:
            return
        try:
            backend = legacy.dashboard_repository(legacy.DATABASE_FILE).backend
            ActivityAuditRepository(backend).record_action(
                actor_id=str(user.get("username") or user.get("id") or "").strip() or None,
                actor_name=str(
                    user.get("display_name")
                    or user.get("name")
                    or user.get("username")
                    or ""
                ).strip() or None,
                actor_role=str(user.get("role") or "").strip() or None,
                action=action,
                category="authentication",
                result="success",
                summary=(
                    "Login realizado com sucesso."
                    if action == "auth.login"
                    else "Logout realizado com sucesso."
                ),
                target_type="browser_session",
                target_id=area,
                remote_address=(
                    handler.client_address[0]
                    if getattr(handler, "client_address", None)
                    else None
                ),
                user_agent=str(handler.headers.get("User-Agent") or "").strip() or None,
            )
        except Exception:
            # Auditoria não deve derrubar uma autenticação válida,
            # mas os testes funcionais verificam sua persistência.
            pass

    def browser_session_get(self):
        path = urlparse(self.path).path

        if path == SESSION_PATH:
            area = "controller"
        elif path == CUSTOMER_LOGIN_PATH:
            area = "customer"
        else:
            return previous_get(self)

        user = session_user_from_headers(self.headers, area=area)
        if user is None:
            _send(self, 401, {"authenticated": False})
            return

        payload = {
            "authenticated": True,
            "username": user.get("username", ""),
            "role": user.get("role", ""),
            "scope_id": user.get("scope_id", ""),
        }

        if user.get("customer_id") is not None:
            payload["customer_id"] = user["customer_id"]

        if user.get("customer_code"):
            payload["customer_code"] = user["customer_code"]

        _send(self, 200, payload)

    def browser_session_post(self):
        path = urlparse(self.path).path
        if path == ADMIN_LOGIN_PATH:
            if not _login_allowed(self, "controller-browser-login"):
                return
            user = controller_credential_authenticator(self.headers)
            if user is None or user.get("role") not in {"admin", "controller", "operator"}:
                revoke_session(
                    session_token_from_headers(self.headers, area="controller")
                )
                _send(
                    self,
                    401,
                    {"error": "invalid_credentials", "message": "Usuário ou senha inválidos."},
                    cookie=expired_cookie_header(area="controller"),
                )
                return
            token = _replace_session(self, user, area="controller")
            audit_auth(self, user, "auth.login", area="controller")
            _send(
                self,
                200,
                {"authenticated": True, "role": user.get("role"), "username": user.get("username")},
                cookie=cookie_header(token, area="controller"),
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
                revoke_session(
                    session_token_from_headers(self.headers, area="customer")
                )
                _send(
                    self,
                    401,
                    {"error": "invalid_credentials", "message": "Usuário ou senha inválidos."},
                    cookie=expired_cookie_header(area="customer"),
                )
                return
            token = _replace_session(self, user, area="customer")
            audit_auth(self, user, "auth.login", area="customer")
            _send(
                self,
                200,
                {"authenticated": True, "role": "customer", "username": user.get("username")},
                cookie=cookie_header(token, area="customer"),
            )
            return

        if path == LOGOUT_PATH:
            user = session_user_from_headers(self.headers, area="controller")
            revoke_session(
                session_token_from_headers(self.headers, area="controller")
            )
            audit_auth(self, user, "auth.logout", area="controller")
            _send(
                self,
                200,
                {"authenticated": False},
                cookie=expired_cookie_header(area="controller"),
            )
            return

        if path == CUSTOMER_LOGOUT_PATH:
            user = session_user_from_headers(self.headers, area="customer")
            revoke_session(
                session_token_from_headers(self.headers, area="customer")
            )
            audit_auth(self, user, "auth.logout", area="customer")
            _send(
                self,
                200,
                {"authenticated": False},
                cookie=expired_cookie_header(area="customer"),
            )
            return

        return previous_post(self)

    legacy.DashboardHandler.do_GET = browser_session_get
    legacy.DashboardHandler.do_POST = browser_session_post


__all__ = [
    "ADMIN_LOGIN_PATH",
    "BRIDGE_PATH",
    "CUSTOMER_LOGIN_PATH",
    "CUSTOMER_LOGOUT_PATH",
    "LOGOUT_PATH",
    "SESSION_PATH",
    "install_browser_session_http",
]
