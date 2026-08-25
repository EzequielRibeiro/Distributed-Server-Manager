#!/usr/bin/env python3
"""Final HTTP audit layer and Admin-only activity-log query surface."""
from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from controller_session import (
    expired_cookie_header,
    revoke_session,
    session_token_from_headers,
    session_user_from_headers,
)
from dashboard_activity_repository import DashboardActivityRepository

ACTIVITY_PAGE = "/activity-log.html"
ACTIVITY_API = "/api/admin/activity-log"
ACTIVITY_OPTIONS_API = "/api/admin/activity-log/options"
LOGOUT_API = "/api/auth/logout"

# High-frequency machine/polling routes are operational telemetry, not a human
# Dashboard action. They already have observability/event persistence elsewhere.
_NON_HUMAN_ROUTES = {
    "/ping",
    "/health",
    "/api/controller/telemetry",
    "/api/realtime/events",
}

_CATEGORY_PREFIXES = (
    ("/api/auth/", "authentication"),
    ("/api/users", "system_users"),
    ("/api/admin/custom", "customers"),
    ("/api/customer", "customers"),
    ("/api/catalog", "catalog"),
    ("/api/agent", "agents"),
    ("/api/instance", "instances"),
    ("/api/backup", "backup"),
    ("/api/content", "content"),
    ("/api/automation", "automation"),
    ("/api/broadcast", "broadcast"),
    ("/api/infrastructure", "infrastructure"),
    ("/api/events", "events"),
    ("/api/config", "configuration"),
)


def _requested_username(headers) -> str | None:
    auth = str(headers.get("Authorization") or "")
    if not auth.startswith("Basic "):
        return None
    try:
        raw = base64.b64decode(auth[6:], validate=True).decode("utf-8")
        username, separator, _password = raw.partition(":")
        if separator:
            return username.strip().lower() or None
    except Exception:
        return None
    return None


def _session_id(token: str | None) -> str | None:
    if not token:
        return None
    # Never persist the actual session credential.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def _category(path: str) -> str:
    for prefix, category in _CATEGORY_PREFIXES:
        if path.startswith(prefix):
            return category
    if path.endswith(".html") or path in {"/", "/index.html"}:
        return "navigation"
    return "dashboard"


def _activity(method: str, path: str) -> str:
    if path == "/api/auth/login":
        return "LOGIN"
    if path == LOGOUT_API:
        return "LOGOUT"
    if path.endswith(".html") or path in {"/", "/index.html"}:
        return "PAGE_VIEW"
    normalized = path.strip("/").replace("/", ".").replace("-", "_") or "root"
    return f"{method.upper()}:{normalized}"[:191]


def _should_record(method: str, path: str, user) -> bool:
    if path in _NON_HUMAN_ROUTES:
        return False
    if path == "/api/auth/login":
        return True
    if path == LOGOUT_API:
        return True
    if user is None:
        return False
    if path.startswith("/api/"):
        return True
    return method == "GET" and (path.endswith(".html") or path in {"/", "/index.html"})


def install_dashboard_activity_audit(legacy, authenticate) -> None:
    """Install the outermost Dashboard HTTP activity logger."""
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST
    previous_put = getattr(legacy.DashboardHandler, "do_PUT", None)
    previous_delete = getattr(legacy.DashboardHandler, "do_DELETE", None)
    previous_send_response = legacy.DashboardHandler.send_response
    previous_send_header = legacy.DashboardHandler.send_header

    legacy.STATIC_FILES.update({
        ACTIVITY_PAGE: legacy.WEB_DIR / "activity-log.html",
        "/activity-log.js": legacy.WEB_DIR / "activity-log.js",
    })

    def backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def repository():
        return DashboardActivityRepository(backend())

    def identity(headers):
        """Resolve browser navigation by cookie and API activity by Basic auth."""
        session_user = session_user_from_headers(headers)
        if session_user is not None:
            return session_user
        return authenticate(headers)

    def send_response(self, code, message=None):
        self._activity_status_code = int(code)
        return previous_send_response(self, code, message)

    def send_header(self, keyword, value):
        if str(keyword).lower() == "set-cookie" and "capivara_session=" in str(value):
            raw = str(value).split("capivara_session=", 1)[1].split(";", 1)[0]
            if raw:
                self._activity_response_session = raw
        return previous_send_header(self, keyword, value)

    legacy.DashboardHandler.send_response = send_response
    legacy.DashboardHandler.send_header = send_header

    def _admin(self):
        user = identity(self.headers)
        if user is None:
            self.unauthorized()
            return None
        if str(user.get("role") or "").lower() != "admin":
            self.send_json(403, {"error": "forbidden", "message": "Acesso exclusivo de administradores."})
            return None
        return user

    def _record(self, method: str, path: str, user_before, requested_username: str | None):
        status = int(getattr(self, "_activity_status_code", 500))
        user_after = identity(self.headers)
        user = user_after or user_before
        username = (user or {}).get("username") or requested_username
        role = (user or {}).get("role")
        request_token = session_token_from_headers(self.headers)
        response_token = getattr(self, "_activity_response_session", None)
        sid = _session_id(response_token or request_token)
        if not _should_record(method, path, user):
            return
        try:
            repository().record(
                username=str(username) if username else None,
                role=str(role) if role else None,
                session_id=sid,
                activity=_activity(method, path),
                category=_category(path),
                result="success" if 200 <= status < 400 else ("denied" if status in {401, 403} else "error"),
                method=method,
                path=path,
                status_code=status,
                remote_address=(self.client_address[0] if getattr(self, "client_address", None) else None),
                user_agent=str(self.headers.get("User-Agent") or "")[:1024] or None,
            )
        except Exception:
            # Auditing must never make the Dashboard action fail; persistence
            # failures remain visible through normal service logging/monitoring.
            pass

    def _prepare(self):
        self._activity_status_code = 500
        self._activity_response_session = None
        path = urlparse(self.path).path
        user = identity(self.headers)
        requested = _requested_username(self.headers)
        return path, user, requested

    def do_get(self):
        path, user, requested = _prepare(self)
        if path == ACTIVITY_PAGE:
            if _admin(self) is None:
                return
            self.send_file(legacy.WEB_DIR / "activity-log.html")
            _record(self, "GET", path, user, requested)
            return
        if path in {ACTIVITY_API, ACTIVITY_OPTIONS_API}:
            admin = _admin(self)
            if admin is None:
                return
            query = parse_qs(urlparse(self.path).query)
            repo = repository()
            if path == ACTIVITY_OPTIONS_API:
                self.send_json(200, repo.filter_options())
            else:
                def one(name):
                    return (query.get(name) or [None])[0]
                try:
                    limit = int(one("limit") or 200)
                except ValueError:
                    limit = 200
                rows = repo.search(
                    username=one("username"),
                    category=one("category"),
                    activity=one("activity"),
                    result=one("result"),
                    start_at=one("start_at"),
                    end_at=one("end_at"),
                    limit=limit,
                )
                self.send_json(200, {"activities": rows})
            _record(self, "GET", path, user, requested)
            return
        try:
            previous_get(self)
        finally:
            _record(self, "GET", path, user, requested)

    def do_post(self):
        path, user, requested = _prepare(self)
        if path == LOGOUT_API:
            if user is None:
                self.send_json(401, {"error": "unauthorized"})
            else:
                token = session_token_from_headers(self.headers)
                revoke_session(token)
                body = b'{"logged_out":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", expired_cookie_header())
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            _record(self, "POST", path, user, requested)
            return
        try:
            previous_post(self)
        finally:
            _record(self, "POST", path, user, requested)

    def do_put(self):
        path, user, requested = _prepare(self)
        try:
            if previous_put is not None:
                previous_put(self)
            else:
                self.send_json(404, {"error": "not_found"})
        finally:
            _record(self, "PUT", path, user, requested)

    def do_delete(self):
        path, user, requested = _prepare(self)
        try:
            if previous_delete is not None:
                previous_delete(self)
            else:
                self.send_json(404, {"error": "not_found"})
        finally:
            _record(self, "DELETE", path, user, requested)

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post
    legacy.DashboardHandler.do_PUT = do_put
    legacy.DashboardHandler.do_DELETE = do_delete


__all__ = [
    "ACTIVITY_PAGE",
    "ACTIVITY_API",
    "ACTIVITY_OPTIONS_API",
    "LOGOUT_API",
    "install_dashboard_activity_audit",
]
