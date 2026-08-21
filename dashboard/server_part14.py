#!/usr/bin/env python3
"""Phase 21 integration: Universal Event Platform timeline API and UI."""

from __future__ import annotations

from urllib.parse import urlparse

import server_part13 as integration
from timeline_http import TIMELINE_PATH, dispatch_timeline_get

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_authenticate = integration._authenticate
TIMELINE_UI_PATH = "/js/timeline-ui.js"
TIMELINE_SCRIPT_TAG = '<script src="/js/timeline-ui.js"></script>'
legacy.STATIC_FILES[TIMELINE_UI_PATH] = legacy.WEB_DIR / "js" / "timeline-ui.js"


def _backend():
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _serve_phase21_index(self):
    """Serve the existing dashboard shell with the modular timeline UI loaded.

    This keeps Phase 21 integration out of dashboard/server.py while the legacy
    dashboard shell is progressively decomposed.
    """

    try:
        html = (legacy.WEB_DIR / "index.html").read_text(encoding="utf-8")
    except OSError:
        self.send_error(404)
        return

    if TIMELINE_SCRIPT_TAG not in html:
        html = html.replace("</body>", f"{TIMELINE_SCRIPT_TAG}\n</body>")

    body = html.encode("utf-8")
    self.send_response(200)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(body)


def integrated_get(self):
    parsed = urlparse(self.path)

    if parsed.path in {"/", "/index.html"}:
        return _serve_phase21_index(self)

    if parsed.path != TIMELINE_PATH:
        return _previous_get(self)

    user = _authenticate(self.headers)
    if user is None:
        self.unauthorized()
        return

    result = dispatch_timeline_get(
        parsed.path,
        parsed.query,
        user=user,
        backend=_backend(),
    )
    if result is None:
        return _previous_get(self)

    status, body = result
    self.send_json(status, body)


legacy.DashboardHandler.do_GET = integrated_get


def run():
    legacy.run()


if __name__ == "__main__":
    run()
