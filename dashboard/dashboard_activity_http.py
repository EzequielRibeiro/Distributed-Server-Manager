#!/usr/bin/env python3
"""Admin-only semantic activity-log surface and explicit auth audit."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from activity_audit_repository import ActivityAuditRepository
from activity_humanizer import humanize
from controller_session import expired_cookie_header, revoke_session, session_token_from_headers, session_user_from_headers

ACTIVITY_PAGE = "/activity-log.html"
ACTIVITY_API = "/api/admin/activity-log"
ACTIVITY_OPTIONS_API = "/api/admin/activity-log/options"
ACTIVITY_ACTORS_API = "/api/admin/activity-log/actors"
LOGIN_API = "/api/auth/login"
LOGOUT_API = "/api/auth/logout"


def install_dashboard_activity_audit(legacy, authenticate) -> None:
    """Install semantic activity audit without generic HTTP request logging."""
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    legacy.STATIC_FILES.update({
        ACTIVITY_PAGE: legacy.WEB_DIR / "activity-log.html",
        "/activity-log.js": legacy.WEB_DIR / "activity-log.js",
    })

    def backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def repository():
        return ActivityAuditRepository(backend())

    def identity(headers):
        return session_user_from_headers(headers) or authenticate(headers)

    def record_auth(user, action, self):
        if user is None:
            return
        who = str(user.get("username") or user.get("id") or "").strip() or None
        repository().record_action(
            actor_id=who,
            actor_name=str(user.get("display_name") or user.get("name") or who or "Operador"),
            actor_role=str(user.get("role") or "") or None,
            action=action,
            category="authentication",
            result="success",
            summary=humanize(action, user=user),
            remote_address=(self.client_address[0] if getattr(self, "client_address", None) else None),
            user_agent=str(self.headers.get("User-Agent") or "")[:1024] or None,
        )

    def admin(self):
        user = identity(self.headers)
        if user is None:
            self.unauthorized()
            return None
        if str(user.get("role") or "").lower() != "admin":
            self.send_json(403, {"error": "forbidden", "message": "Acesso exclusivo de administradores."})
            return None
        return user

    def do_get(self):
        path = urlparse(self.path).path
        if path == ACTIVITY_PAGE:
            if admin(self) is None:
                return
            self.send_file(legacy.WEB_DIR / "activity-log.html")
            return
        if path in {ACTIVITY_API, ACTIVITY_OPTIONS_API, ACTIVITY_ACTORS_API}:
            if admin(self) is None:
                return
            repo = repository()
            if path == ACTIVITY_OPTIONS_API:
                self.send_json(200, repo.filter_options())
                return
            query = parse_qs(urlparse(self.path).query)
            one = lambda name: (query.get(name) or [None])[0]
            if path == ACTIVITY_ACTORS_API:
                try:
                    limit = int(one("limit") or 100)
                    offset = int(one("offset") or 0)
                    show_all = str(one("show_all") or "").strip().lower() in {"1", "true", "yes", "on"}
                    result = repo.actor_directory(
                        query=str(one("q") or ""),
                        role=one("role"),
                        limit=limit,
                        offset=offset,
                        include_all=show_all,
                    )
                except (TypeError, ValueError) as exc:
                    self.send_json(400, {"error": "invalid_request", "message": str(exc)})
                    return
                self.send_json(200, result)
                return
            try:
                limit = int(one("limit") or 200)
            except ValueError:
                limit = 200
            rows = repo.search(
                actor_id=one("actor_id") or one("username"),
                actor_role=one("actor_role") or one("role"),
                category=one("category"),
                action=one("action") or one("activity"),
                result=one("result"),
                target_type=one("target_type"),
                target_id=one("target_id"),
                start_at=one("start_at"),
                end_at=one("end_at"),
                limit=limit,
            )
            self.send_json(200, {"activities": rows})
            return
        return previous_get(self)

    def do_post(self):
        path = urlparse(self.path).path
        if path == LOGIN_API:
            captured = {"status": None}
            original_send_response = self.send_response

            def capture_status(code, *args, **kwargs):
                captured["status"] = int(code)
                return original_send_response(code, *args, **kwargs)

            self.send_response = capture_status
            try:
                previous_post(self)
            finally:
                self.send_response = original_send_response
            if captured["status"] == 200:
                record_auth(authenticate(self.headers), "auth.login", self)
            return

        if path != LOGOUT_API:
            return previous_post(self)
        user = identity(self.headers)
        if user is None:
            self.send_json(401, {"error": "unauthorized"})
            return
        record_auth(user, "auth.logout", self)
        revoke_session(session_token_from_headers(self.headers))
        body = b'{"logged_out":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", expired_cookie_header())
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = [
    "ACTIVITY_PAGE",
    "ACTIVITY_API",
    "ACTIVITY_OPTIONS_API",
    "ACTIVITY_ACTORS_API",
    "LOGIN_API",
    "LOGOUT_API",
    "install_dashboard_activity_audit",
]
