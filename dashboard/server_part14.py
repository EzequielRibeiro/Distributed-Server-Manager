#!/usr/bin/env python3
"""D9-D15 Operations Center composition layer."""
from __future__ import annotations

from urllib.parse import urlparse

import server_part13 as integration
from operations_center_http import OPERATIONS_PATH, dispatch_operations_get, dispatch_operations_post

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_previous_post = legacy.DashboardHandler.do_POST

OPERATIONS_FILES = {
    "/operations.html": legacy.WEB_DIR / "operations.html",
    "/operations.js": legacy.WEB_DIR / "operations.js",
    "/operations.css": legacy.WEB_DIR / "operations.css",
}
legacy.STATIC_FILES.update(OPERATIONS_FILES)
integration.SYSTEM_PASSWORD_GATED_PAGES.add("/operations.html")


def integrated_get(self):
    parsed = urlparse(self.path)
    path = parsed.path
    if path == "/operations.html":
        if integration._require_session_page(self, path) is None:
            return
        self.send_file(OPERATIONS_FILES[path])
        return
    if path in {"/operations.js", "/operations.css"}:
        self.send_file(OPERATIONS_FILES[path])
        return
    if path == OPERATIONS_PATH:
        user = integration._user(self)
        if user is None:
            return
        status, body = dispatch_operations_get(path, parsed.query, user=user, backend=integration._backend())
        self.send_json(status, body)
        return
    return _previous_get(self)


def integrated_post(self):
    parsed = urlparse(self.path)
    path = parsed.path
    if path == OPERATIONS_PATH:
        user = integration._user(self)
        if user is None:
            return
        payload, error = integration._payload(self)
        if error:
            self.send_json(400, error)
            return
        status, body = dispatch_operations_post(path, payload, user=user, backend=integration._backend())
        self.send_json(status, body)
        return
    return _previous_post(self)


legacy.DashboardHandler.do_GET = integrated_get
legacy.DashboardHandler.do_POST = integrated_post


def run():
    legacy.run()


if __name__ == "__main__":
    run()
