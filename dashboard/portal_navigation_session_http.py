#!/usr/bin/env python3
"""Final browser-navigation guard for simultaneous Controller and Customer sessions.

Normal top-level browser navigation and passive subresource requests cannot
attach X-Capivara-Auth-Area. This wrapper therefore resolves the authentication
domain from known portal paths before legacy handlers can see both cookies and
fail closed as ambiguous. API requests continue to use explicit area headers.
"""
from __future__ import annotations

from urllib.parse import urlparse

from controller_session import session_user_from_headers

CONTROLLER_PAGES = {
    "/dashboard-v3.html", "/activity-log.html", "/customers.html", "/customer-create.html",
    "/customer-contract-create.html", "/users.html", "/system.html",
    "/infrastructure.html", "/regions.html", "/datacenters.html",
    "/placement.html", "/agents.html", "/add-agent.html",
    "/add-agent-linux.html", "/add-agent-windows.html", "/agent-details.html",
    "/agent-observability.html", "/servers.html", "/catalog.html",
    "/game-profiles.html", "/operations.html", "/observability.html",
    "/alerts.html", "/events.html", "/monitoring.html",
    "/controller-logs.html", "/diagnostics.html", "/help.html",
}

CONTROLLER_ASSETS = {
    "/components/sidebar-v3.html", "/sidebar-v3.js",
    "/dashboard-home-v3.css", "/dashboard-home-v3.js",
    "/dashboard-node-overview.css", "/dashboard-node-overview.js",
    "/telemetry-widgets.css", "/telemetry-widgets.js",
    "/catalog-v2.css", "/activity-log.js", "/customer-admin.css",
    "/customers.js", "/users.js", "/system.css", "/system.js",
    "/infrastructure-v3.css", "/infrastructure-v3.js",
    "/agents-v3.css", "/agents-v3.js", "/agent-steam-status.css",
    "/agent-updates-v3.css", "/agent-updates-v3.js", "/add-agent-v3.css",
    "/add-agent-page.js", "/agent-installation.js", "/agent-installation-wizard.js",
    "/agent-details.css", "/agent-details.js", "/agent-details-sidebar.js", "/agent-storage-pools.css",
    "/agent-storage-pools.js", "/storage-pool-source-cleanup.js",
    "/agent-observability.css", "/agent-observability.js",
    "/agent-queue-details-state.js", "/servers.css", "/servers.js",
    "/catalog-page.css", "/catalog-installation.css", "/catalog-page.js",
    "/game-profiles.css", "/game-profiles.js", "/operations.css",
    "/operations.js", "/observability.css", "/observability.js",
    "/help.css", "/help.js",
}

CUSTOMER_PAGES = {
    "/customer.html", "/contract-demo.html", "/customer-instance.html",
    "/customer-members.html", "/customer-account.html", "/customer-backups.html",
    "/customer-integrations.html", "/customer-change-password.html",
}

# Customer pages also load passive JS/CSS requests without an auth-area header.
# Resolve those assets explicitly with the Customer cookie, otherwise a browser
# holding both Controller and Customer sessions reaches the legacy ambiguous
# authentication path and the shell stays forever in its loading state.
CUSTOMER_ASSETS = {
    "/customer.css", "/customer.js", "/customer-core.js", "/customer-navigation.js",
    "/customer-profile.js", "/customer-email-change.js", "/customer-placement-selector.js",
    "/runtime-selector.js", "/create-server-wizard.css", "/create-server-wizard.js",
    "/customer-instance.js", "/customer-instance-v2.js", "/customer-instance-v2-wrapper.js",
    "/customer-instance-events.css", "/customer-instance-events.js",
    "/customer-instance-activity.js", "/customer-instance-connection.js",
    "/customer-instance-delete.js", "/customer-backup-transfer.js",
    "/customer-team.css", "/customer-members.js", "/customer-account.js",
    "/customer-backups.js", "/customer-integrations.css", "/customer-integrations.js",
}


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


def install_portal_navigation_session_guard(legacy) -> None:
    previous_get = legacy.DashboardHandler.do_GET

    def guarded_get(self):
        path = urlparse(self.path).path
        if path in CONTROLLER_PAGES or path in CONTROLLER_ASSETS:
            user = _controller_user(self)
            if user is None:
                if path in CONTROLLER_PAGES:
                    _redirect(self, "/login.html")
                else:
                    self.send_json(401, {"error": "authentication_required"})
                return
            if user is False:
                self.send_json(403, {"error": "forbidden"})
                return
            target = legacy.STATIC_FILES.get(path)
            if target is not None:
                self.send_file(target)
                return

        if path in CUSTOMER_PAGES or path in CUSTOMER_ASSETS:
            user = _customer_user(self)
            if user is None:
                if path in CUSTOMER_PAGES:
                    _redirect(self, "/customer-login.html")
                else:
                    self.send_json(401, {"error": "authentication_required"})
                return
            if user is False:
                self.send_json(403, {"error": "forbidden"})
                return
            target = legacy.STATIC_FILES.get(path)
            if target is not None:
                self.send_file(target)
                return

        return previous_get(self)

    legacy.DashboardHandler.do_GET = guarded_get


__all__ = [
    "CONTROLLER_PAGES", "CONTROLLER_ASSETS", "CUSTOMER_PAGES", "CUSTOMER_ASSETS",
    "install_portal_navigation_session_guard",
]
