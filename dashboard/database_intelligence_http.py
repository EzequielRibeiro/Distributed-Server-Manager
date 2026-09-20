#!/usr/bin/env python3
"""HTTP/UI adapter for DB1-DB6 Database Intelligence."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from database_intelligence_api import database_intelligence, database_maintenance

DATABASE_INTELLIGENCE_PATH = "/api/admin/database-intelligence"
DATABASE_INTELLIGENCE_ACTION_PATH = "/api/admin/database-intelligence/action"
DATABASE_INTELLIGENCE_PAGE = "/database-intelligence.html"
DATABASE_INTELLIGENCE_ASSETS = {
    "/database-intelligence.js",
    "/database-intelligence.css",
}


def dispatch_database_intelligence_get(path: str, query: str, *, user, backend):
    if path != DATABASE_INTELLIGENCE_PATH:
        return 404, {"error": "not_found"}
    values = parse_qs(query or "")
    mode = (values.get("mode") or ["overview"])[0]
    try:
        days = int((values.get("days") or ["90"])[0])
    except ValueError:
        days = 90
    try:
        return 200, database_intelligence(user=user, backend=backend, mode=mode, days=days)
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}


def dispatch_database_intelligence_post(path: str, payload: dict, *, user, backend):
    if path != DATABASE_INTELLIGENCE_ACTION_PATH:
        return 404, {"error": "not_found"}
    values = payload if isinstance(payload, dict) else {}
    try:
        return 200, database_maintenance(
            user=user,
            backend=backend,
            action=str(values.get("action") or ""),
            payload=values,
        )
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}


def install_database_intelligence_http(legacy, authenticate) -> None:
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST
    legacy.STATIC_FILES.update({
        DATABASE_INTELLIGENCE_PAGE: legacy.WEB_DIR / "database-intelligence.html",
        "/database-intelligence.js": legacy.WEB_DIR / "database-intelligence.js",
        "/database-intelligence.css": legacy.WEB_DIR / "database-intelligence.css",
    })

    def _backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def database_intelligence_get(self):
        parsed = urlparse(self.path)
        if parsed.path in DATABASE_INTELLIGENCE_ASSETS:
            self.send_file(legacy.STATIC_FILES[parsed.path])
            return
        if parsed.path == DATABASE_INTELLIGENCE_PAGE:
            user = authenticate(self.headers)
            if user is None:
                self.unauthorized()
                return
            if str(user.get("role") or "").lower() not in {"admin", "controller"}:
                self.forbidden()
                return
            self.send_file(legacy.STATIC_FILES[DATABASE_INTELLIGENCE_PAGE])
            return
        if parsed.path != DATABASE_INTELLIGENCE_PATH:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        status, body = dispatch_database_intelligence_get(
            parsed.path, parsed.query, user=user, backend=_backend()
        )
        self.send_json(status, body)

    def database_intelligence_post(self):
        parsed = urlparse(self.path)
        if parsed.path != DATABASE_INTELLIGENCE_ACTION_PATH:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        try:
            payload = self.read_json_body()
        except ValueError as exc:
            self.send_json(400, {"error": "invalid_request", "message": str(exc)})
            return
        status, body = dispatch_database_intelligence_post(
            parsed.path, payload, user=user, backend=_backend()
        )
        self.send_json(status, body)

    legacy.DashboardHandler.do_GET = database_intelligence_get
    legacy.DashboardHandler.do_POST = database_intelligence_post


__all__ = [
    "DATABASE_INTELLIGENCE_PATH",
    "DATABASE_INTELLIGENCE_ACTION_PATH",
    "DATABASE_INTELLIGENCE_PAGE",
    "DATABASE_INTELLIGENCE_ASSETS",
    "dispatch_database_intelligence_get",
    "dispatch_database_intelligence_post",
    "install_database_intelligence_http",
]
