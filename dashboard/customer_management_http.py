#!/usr/bin/env python3
"""HTTP composition for the separated Customer management Dashboard pages."""
from __future__ import annotations

from urllib.parse import urlparse

from controller_session import session_user_from_headers

CUSTOMER_MANAGEMENT_PAGES = {
    "/customers.html": "customers.html",
    "/customer-create.html": "customer-create.html",
    "/customer-admin.html": "customer-admin.html",
    "/customer-contract-create.html": "customer-contract-create.html",
}

CUSTOMER_MANAGEMENT_ASSETS = {
    "/customers.js": "customers.js",
    "/customer-create.js": "customer-create.js",
    "/customer-admin.js": "customer-admin.js",
    "/customer-contract-create.js": "customer-contract-create.js",
    "/customer-management-shell.js": "customer-management-shell.js",
    "/customer-management.css": "customer-management.css",
}

_PAGE_ROLES = {
    "/customers.html": {"admin", "controller", "operator"},
    "/customer-create.html": {"admin", "controller"},
    "/customer-admin.html": {"admin", "controller", "operator"},
    "/customer-contract-create.html": {"admin", "controller", "operator"},
}


def install_customer_management_dashboard(legacy) -> None:
    """Register assets and add session/RBAC enforcement without touching server.py."""
    files = {
        path: legacy.WEB_DIR / filename
        for path, filename in (CUSTOMER_MANAGEMENT_PAGES | CUSTOMER_MANAGEMENT_ASSETS).items()
    }
    legacy.STATIC_FILES.update(files)
    previous_get = legacy.DashboardHandler.do_GET

    def customer_management_get(self):
        path = urlparse(self.path).path
        if path in CUSTOMER_MANAGEMENT_PAGES:
            user = session_user_from_headers(self.headers, area="controller")
            if user is None:
                self.send_response(302)
                self.send_header("Location", "/login.html")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            role = str(user.get("role") or "").lower()
            if role not in _PAGE_ROLES[path]:
                self.forbidden()
                return
            self.send_file(files[path])
            return
        if path in CUSTOMER_MANAGEMENT_ASSETS:
            self.send_file(files[path])
            return
        return previous_get(self)

    legacy.DashboardHandler.do_GET = customer_management_get


__all__ = [
    "CUSTOMER_MANAGEMENT_ASSETS",
    "CUSTOMER_MANAGEMENT_PAGES",
    "install_customer_management_dashboard",
]
