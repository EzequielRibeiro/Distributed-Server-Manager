#!/usr/bin/env python3
"""Phase 18/19 integration: Agent update administration and Windows bootstrap."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import server_part12 as integration
from agent_update_http import (
    CHANNEL_PATH,
    ROLLOUT_PATH,
    STATUS_PATH,
    dispatch_update_get,
    dispatch_update_post,
)

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_previous_post = legacy.DashboardHandler.do_POST
_authenticate = integration._authenticate
ROOT_DIR = Path(__file__).resolve().parents[1]
WINDOWS_INSTALL_PATH = "/agent/install.ps1"
WINDOWS_INSTALL_FILE = ROOT_DIR / "agents" / "windows" / "installer" / "bootstrap-release.ps1"
VERSION_FILE = ROOT_DIR / "version"
legacy.STATIC_FILES["/agent-updates.js"] = legacy.WEB_DIR / "agent-updates.js"


def _user(self):
    user = _authenticate(self.headers)
    if user is None:
        self.unauthorized()
    return user


def _serve_windows_bootstrap(self):
    try:
        script = WINDOWS_INSTALL_FILE.read_text(encoding="utf-8")
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        self.send_error(404)
        return
    prefix = f'$env:CAPIVARA_RELEASE_TAG = if ($env:CAPIVARA_RELEASE_TAG) {{ $env:CAPIVARA_RELEASE_TAG }} else {{ "v{version}" }}\r\n'
    body = (prefix + script).encode("utf-8")
    self.send_response(200)
    self.send_header("Content-Type", "text/plain; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(body)


def integrated_get(self):
    parsed = urlparse(self.path)
    if parsed.path == WINDOWS_INSTALL_PATH:
        return _serve_windows_bootstrap(self)
    if parsed.path != STATUS_PATH:
        return _previous_get(self)
    user = _user(self)
    if user is None:
        return
    query = parse_qs(parsed.query)
    status, body = dispatch_update_get(
        parsed.path,
        user=user,
        backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
        agent_id=(query.get("agent_id") or [None])[0],
    )
    self.send_json(status, body)


def integrated_post(self):
    parsed = urlparse(self.path)
    if parsed.path not in {ROLLOUT_PATH, CHANNEL_PATH}:
        return _previous_post(self)
    user = _user(self)
    if user is None:
        return
    try:
        payload = self.read_json_body()
    except ValueError:
        self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."})
        return
    status, body = dispatch_update_post(
        parsed.path,
        payload,
        user=user,
        backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
    )
    self.send_json(status, body)


legacy.DashboardHandler.do_GET = integrated_get
legacy.DashboardHandler.do_POST = integrated_post


def run():
    legacy.run()


if __name__ == "__main__":
    run()
