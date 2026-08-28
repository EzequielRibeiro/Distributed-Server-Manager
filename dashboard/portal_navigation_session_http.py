#!/usr/bin/env python3
"""Final browser-navigation guard for simultaneous Controller and Customer sessions.

Normal top-level browser navigation cannot attach X-Capivara-Auth-Area. This
wrapper therefore resolves the authentication domain from the requested page
path before legacy handlers can see both cookies and fail closed as ambiguous.
API requests continue to use explicit area headers.
"""
from __future__ import annotations

from urllib.parse import urlparse

from controller_session import session_user_from_headers

CONTROLLER_PAGES = {
    "/activity-log.html",
    "/customers.html",
    "/customer-create.html",
    "/customer-contract-create.html",
    "/users.html",
    "/system.html",
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
    "/game-profiles.html",
    "/operations.html",
    "/observability.html",
    "/alerts.html",
    "/events.html",
    "/monitoring.html",
    "/controller-logs.html",
    "/diagnostics.html",
    "/help.html",
}

CUSTOMER_PAGES = {
    "/contract-demo.html",
}


def _redirect(handler, location: str) -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def install_portal_navigation_session_guard(legacy) -> None:
    previous_get = legacy.DashboardHandler.do_GET

    def guarded_get(self):
        path = urlparse(self.path).path

        if path in CONTROLLER_PAGES:
            user = session_user_from_headers(self.headers, area="controller")
            if user is None:
                _redirect(self, "/login.html")
                return
            if str(user.get("role") or "").lower() not in {"admin", "controller", "operator"}:
                self.send_json(403, {"error": "forbidden"})
                return
            target = legacy.STATIC_FILES.get(path)
            if target is not None:
                self.send_file(target)
                return

        if path in CUSTOMER_PAGES:
            user = session_user_from_headers(self.headers, area="customer")
            if user is None:
                _redirect(self, "/customer-login.html")
                return
            if str(user.get("role") or "").lower() != "customer":
                self.send_json(403, {"error": "forbidden"})
                return
            target = legacy.STATIC_FILES.get(path)
            if target is not None:
                self.send_file(target)
                return

        return previous_get(self)

    legacy.DashboardHandler.do_GET = guarded_get


__all__ = [
    "CONTROLLER_PAGES",
    "CUSTOMER_PAGES",
    "install_portal_navigation_session_guard",
]
