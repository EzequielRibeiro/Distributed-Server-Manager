#!/usr/bin/env python3
"""HTTP/UI adapter for administrative YARA-X security."""
from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

from json_serialization import to_json_compatible
from yarax_admin_operation_api import list_operations
from yarax_security_api import yarax_security_overview

YARAX_SECURITY_PATH = "/api/admin/security/yara-x"
YARAX_SECURITY_STREAM_PATH = YARAX_SECURITY_PATH + "/stream"
YARAX_SECURITY_PAGE = "/admin-security-yarax.html"
YARAX_SECURITY_ASSETS = {"/admin-security-yarax.js", "/admin-security-yarax.css"}


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


def _sse_frame(event: str, payload: dict, event_id: str | None = None) -> bytes:
    data = json.dumps(to_json_compatible(payload), ensure_ascii=False, separators=(",", ":"))
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.extend(f"data: {line}" for line in data.splitlines() or [""])
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _stream_snapshot(*, user, backend, filters):
    overview = yarax_security_overview(user=user, backend=backend, filters=filters)
    operations = list_operations(
        user=user,
        backend=backend,
        agent_id=filters.get("agent_id"),
        limit=100,
    )
    return {"overview": overview, "operations": operations.get("operations") or []}


def serve_yarax_security_stream(handler, query: str, *, user, backend, timeout: int = 25) -> None:
    values = parse_qs(query or "")
    filters = {key: (value[0] if value else None) for key, value in values.items()}
    first = _stream_snapshot(user=user, backend=backend, filters=filters)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    deadline = time.monotonic() + max(5, min(int(timeout), 30))
    last_signature = ""
    last_ping = 0.0
    try:
        handler.wfile.write(_sse_frame("ready", {"kind": "CapivaraYaraXSecurityStream", "version": 1, "retry_ms": 1500}))
        handler.wfile.flush()
        while time.monotonic() < deadline:
            payload = first if not last_signature else _stream_snapshot(user=user, backend=backend, filters=filters)
            encoded = json.dumps(to_json_compatible(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            signature = hashlib.sha256(encoded).hexdigest()
            if signature != last_signature:
                handler.wfile.write(_sse_frame("yarax-state", payload, signature[:24]))
                handler.wfile.flush()
                last_signature = signature
                last_ping = time.monotonic()
            elif time.monotonic() - last_ping >= 10:
                handler.wfile.write(b": keepalive\n\n")
                handler.wfile.flush()
                last_ping = time.monotonic()
            time.sleep(1.0)
    except (BrokenPipeError, ConnectionResetError, OSError):
        return


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
        if parsed.path in YARAX_SECURITY_ASSETS:
            self.send_file(legacy.STATIC_FILES[parsed.path])
            return
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
        if parsed.path not in {YARAX_SECURITY_PATH, YARAX_SECURITY_STREAM_PATH}:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        if parsed.path == YARAX_SECURITY_STREAM_PATH:
            try:
                return serve_yarax_security_stream(self, parsed.query, user=user, backend=_backend())
            except PermissionError:
                self.forbidden()
                return
            except ValueError as exc:
                self.send_json(400, {"error": "invalid_request", "message": str(exc)})
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
    "YARAX_SECURITY_ASSETS",
    "YARAX_SECURITY_PAGE",
    "YARAX_SECURITY_PATH",
    "YARAX_SECURITY_STREAM_PATH",
    "dispatch_yarax_security_get",
    "serve_yarax_security_stream",
    "install_yarax_security_http",
]
