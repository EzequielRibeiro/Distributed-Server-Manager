#!/usr/bin/env python3
"""HTTP/UI adapter for P8 administrative observability."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from admin_observability_api import consolidated_observability

ADMIN_OBSERVABILITY_PATH = "/api/admin/observability"
ADMIN_OBSERVABILITY_PAGE = "/admin-observability.html"


def dispatch_admin_observability_get(path: str, query: str, *, user, backend):
    if path != ADMIN_OBSERVABILITY_PATH:
        return 404, {"error": "not_found"}
    values = parse_qs(query or "")
    filters = {key: (value[0] if value else None) for key, value in values.items()}
    try:
        return 200, consolidated_observability(user=user, backend=backend, filters=filters)
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}


def install_admin_observability(legacy, authenticate) -> None:
    """Install the P8 route without adding responsibility to server.py."""
    previous_get = legacy.DashboardHandler.do_GET
    legacy.STATIC_FILES.update(
        {
            ADMIN_OBSERVABILITY_PAGE: legacy.WEB_DIR / "admin-observability.html",
            "/admin-observability.js": legacy.WEB_DIR / "admin-observability.js",
            "/admin-observability.css": legacy.WEB_DIR / "admin-observability.css",
        }
    )

    def _backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def p8_get(self):
        parsed = urlparse(self.path)
        if parsed.path == ADMIN_OBSERVABILITY_PAGE:
            user = authenticate(self.headers)
            if user is None:
                self.unauthorized()
                return
            if str(user.get("role") or "").lower() not in {"admin", "controller"}:
                self.forbidden()
                return
            self.send_file(legacy.STATIC_FILES[ADMIN_OBSERVABILITY_PAGE])
            return
        if parsed.path != ADMIN_OBSERVABILITY_PATH:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        status, body = dispatch_admin_observability_get(
            parsed.path,
            parsed.query,
            user=user,
            backend=_backend(),
        )
        self.send_json(status, body)

    legacy.DashboardHandler.do_GET = p8_get


__all__ = [
    "ADMIN_OBSERVABILITY_PATH",
    "ADMIN_OBSERVABILITY_PAGE",
    "dispatch_admin_observability_get",
    "install_admin_observability",
]
