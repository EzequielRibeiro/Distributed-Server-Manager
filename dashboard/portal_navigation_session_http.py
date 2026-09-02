#!/usr/bin/env python3
"""Final browser-navigation/static-asset guard for simultaneous portal sessions.

Normal top-level browser navigation and passive subresource requests cannot
attach X-Capivara-Auth-Area. Resolve the authentication domain from the
canonical static-asset policy before legacy handlers can see both Controller
and Customer cookies and fail closed as ambiguous.
"""
from __future__ import annotations

from urllib.parse import urlparse

from controller_session import session_user_from_headers
from static_asset_policy import (
    CONTROLLER_STATIC_PATHS,
    CUSTOMER_STATIC_PATHS,
    SHARED_PUBLIC_STATIC_PATHS,
)


CONTROLLER_PAGES = frozenset({
    "/",
    "/index.html",
    "/dashboard-v3.html",
    "/activity-log.html",
    "/customers.html",
    "/customer-create.html",
    "/customer-admin.html",
    "/customer-contract-create.html",
    "/users.html",
    "/system.html",
    "/system-change-password.html",
    "/infrastructure.html",
    "/regions.html",
    "/datacenters.html",
    "/placement.html",
    "/agents.html",
    "/add-agent.html",
    "/add-agent-linux.html",
    "/add-agent-windows.html",
    "/agent-details.html",
    "/agent-observability.html",
    "/servers.html",
    "/catalog.html",
    "/catalog-game-create.html",
    "/game-profiles.html",
    "/operations.html",
    "/observability.html",
    "/alerts.html",
    "/events.html",
    "/monitoring.html",
    "/controller-logs.html",
    "/diagnostics.html",
    "/help.html",
})

CUSTOMER_PAGES = frozenset({
    "/customer.html",
    "/contract-demo.html",
    "/customer-instance.html",
    "/customer-members.html",
    "/customer-account.html",
    "/customer-backups.html",
    "/customer-integrations.html",
    "/customer-change-password.html",
})

CONTROLLER_ASSETS = CONTROLLER_STATIC_PATHS - CONTROLLER_PAGES
CUSTOMER_ASSETS = CUSTOMER_STATIC_PATHS - CUSTOMER_PAGES


def _redirect(handler, location: str) -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _controller_user(handler):
    user = session_user_from_headers(handler.headers, area="controller")
    if user is None:
        return None
    if str(user.get("role") or "").lower() not in {"admin", "controller", "operator"}:
        return False
    return user


def _customer_user(handler):
    user = session_user_from_headers(handler.headers, area="customer")
    if user is None:
        return None
    if str(user.get("role") or "").lower() != "customer":
        return False
    return user


def _serve_registered_static(handler, legacy, path: str) -> bool:
    target = legacy.STATIC_FILES.get(path)
    if target is None:
        return False
    handler.send_file(target)
    return True


def install_portal_navigation_session_guard(legacy) -> None:
    previous_get = legacy.DashboardHandler.do_GET

    def guarded_get(self):
        path = urlparse(self.path).path

        if path in SHARED_PUBLIC_STATIC_PATHS:
            if _serve_registered_static(self, legacy, path):
                return
            return previous_get(self)

        if path in CONTROLLER_STATIC_PATHS:
            user = _controller_user(self)
            if user is None:
                if path in CONTROLLER_PAGES:
                    _redirect(self, "/login.html")
                else:
                    self.send_json(401, {"error": "authentication_required", "area": "controller"})
                return
            if user is False:
                self.send_json(403, {"error": "forbidden", "area": "controller"})
                return
            if _serve_registered_static(self, legacy, path):
                return
            return previous_get(self)

        if path in CUSTOMER_STATIC_PATHS:
            user = _customer_user(self)
            if user is None:
                if path in CUSTOMER_PAGES:
                    _redirect(self, "/customer-login.html")
                else:
                    self.send_json(401, {"error": "authentication_required", "area": "customer"})
                return
            if user is False:
                self.send_json(403, {"error": "forbidden", "area": "customer"})
                return
            if _serve_registered_static(self, legacy, path):
                return
            return previous_get(self)

        return previous_get(self)

    legacy.DashboardHandler.do_GET = guarded_get


__all__ = [
    "CONTROLLER_PAGES",
    "CONTROLLER_ASSETS",
    "CUSTOMER_PAGES",
    "CUSTOMER_ASSETS",
    "SHARED_PUBLIC_STATIC_PATHS",
    "install_portal_navigation_session_guard",
]
