#!/usr/bin/env python3
"""Part 8 HTTP integration wrapper for Capivara DSM customer self-service.

Keeps the legacy dashboard server focused on transport while customer account
routing remains delegated to customer_account_http.py.
"""
from __future__ import annotations

from urllib.parse import urlparse

import server as legacy
from customer_account_http import (
    AUTHENTICATED_PATHS,
    PUBLIC_PATHS,
    dispatch_customer_account,
)

CUSTOMER_PUBLIC_FILES = {
    "/customer-login.html": legacy.WEB_DIR / "customer-login.html",
    "/customer-register.html": legacy.WEB_DIR / "customer-register.html",
    "/customer-forgot-password.html": legacy.WEB_DIR / "customer-forgot-password.html",
    "/customer-reset-password.html": legacy.WEB_DIR / "customer-reset-password.html",
    "/customer-auth.css": legacy.WEB_DIR / "customer-auth.css",
    "/customer-auth.js": legacy.WEB_DIR / "customer-auth.js",
}

CUSTOMER_AUTHENTICATED_FILES = {
    "/customer-members.html": legacy.WEB_DIR / "customer-members.html",
    "/customer-members.js": legacy.WEB_DIR / "customer-members.js",
}

legacy.STATIC_FILES.update(CUSTOMER_PUBLIC_FILES)
legacy.STATIC_FILES.update(CUSTOMER_AUTHENTICATED_FILES)

_original_get = legacy.DashboardHandler.do_GET
_original_post = legacy.DashboardHandler.do_POST


def _backend():
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _dispatch(handler, method: str, path: str, *, user, payload=None) -> bool:
    result = dispatch_customer_account(
        method,
        path,
        payload=payload,
        user=user,
        backend=_backend(),
    )
    if result is None:
        return False
    status, body = result
    handler.send_json(status, body)
    return True


def integrated_get(self):
    path = urlparse(self.path).path

    if path in CUSTOMER_PUBLIC_FILES:
        self.send_file(CUSTOMER_PUBLIC_FILES[path])
        return

    if path in AUTHENTICATED_PATHS:
        user = legacy.authenticate(self.headers)
        if not legacy.can_read(user):
            self.unauthorized()
            return
        if _dispatch(self, "GET", path, user=user):
            return

    _original_get(self)


def integrated_post(self):
    path = urlparse(self.path).path

    if path in PUBLIC_PATHS:
        try:
            payload = self.read_json_body()
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
            return
        if _dispatch(self, "POST", path, user=None, payload=payload):
            return

    if path in AUTHENTICATED_PATHS:
        user = legacy.authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        if not legacy.can_write(user):
            self.forbidden()
            return
        try:
            payload = self.read_json_body()
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
            return
        if _dispatch(self, "POST", path, user=user, payload=payload):
            return

    _original_post(self)


legacy.DashboardHandler.do_GET = integrated_get
legacy.DashboardHandler.do_POST = integrated_post


def run():
    legacy.run()


if __name__ == "__main__":
    run()
