#!/usr/bin/env python3
"""HTTP/UI adapter for administrative YARA-X security."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from yarax_security_api import yarax_security_overview

YARAX_SECURITY_PATH = "/api/admin/security/yara-x"
YARAX_SECURITY_PAGE = "/admin-security-yarax.html"


def dispatch_yarax_security_get(path: str, query: str, *, user, backend):
    if path != YARAX_SECURITY_PATH:
        return 404, {"error": "not_found"}
    values = parse_qs(query or "")
    filters = {key: (value[0] if value else None) for key, value in values.items()}
    try:
        return 200, yarax_security_overview(user=user, backend=backend, filters=filters)
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}


def install_yarax_security_http(legacy, authenticate) -> None:
    previous_get = legacy.DashboardHandler.do_GET
    legacy.STATIC_FILES.update(
        {
            YARAX_SECURITY_PAGE: legacy.WEB_DIR / "admin-security-yarax.html",
            "/admin-security-yarax.js": legacy.WEB_DIR / "admin-security-yarax.js",
            "/admin-security-yarax.css": legacy.WEB_DIR / "admin-security-yarax.css",
        }
    )

    def _backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def yarax_get(self):
        parsed = urlparse(self.path)
        if parsed.path == YARAX_SECURITY_PAGE:
            user = authenticate(self.headers)
            if user is None:
                self.unauthorized()
                return
            if str(user.get("role") or "").lower() not in {"admin", "controller"}:
                self.forbidden()
                return
            self.send_file(legacy.STATIC_FILES[YARAX_SECURITY_PAGE])
            return
        if parsed.path != YARAX_SECURITY_PATH:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        status, payload = dispatch_yarax_security_get(
            parsed.path,
            parsed.query,
            user=user,
            backend=_backend(),
        )
        self.send_json(status, payload)

    legacy.DashboardHandler.do_GET = yarax_get


__all__ = [
    "YARAX_SECURITY_PAGE",
    "YARAX_SECURITY_PATH",
    "dispatch_yarax_security_get",
    "install_yarax_security_http",
]
