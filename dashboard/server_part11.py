#!/usr/bin/env python3
"""Phase 11-13 HTTP integration for remote Linux Agents."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import server_part10 as integration
from agent_remote_http import ENROLL_PATH, HEARTBEAT_PATH, dispatch_enroll, dispatch_heartbeat

legacy = integration.legacy
_previous_post = legacy.DashboardHandler.do_POST
_previous_get = legacy.DashboardHandler.do_GET
ROOT_DIR = Path(__file__).resolve().parents[1]
AGENT_INSTALL_PATH = "/agent/install.sh"
AGENT_INSTALL_FILE = ROOT_DIR / "agents" / "linux" / "installer" / "bootstrap-release.sh"


def integrated_get(self):
    path = urlparse(self.path).path
    if path != AGENT_INSTALL_PATH:
        return _previous_get(self)
    try:
        body = AGENT_INSTALL_FILE.read_bytes()
    except OSError:
        self.send_error(404)
        return
    self.send_response(200)
    self.send_header("Content-Type", "text/x-shellscript; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(body)


def integrated_post(self):
    path = urlparse(self.path).path
    if path not in {ENROLL_PATH, HEARTBEAT_PATH}:
        return _previous_post(self)

    try:
        payload = self.read_json_body()
    except ValueError:
        self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."})
        return

    backend = legacy.dashboard_repository(legacy.DATABASE_FILE).backend
    if path == ENROLL_PATH:
        status, body = dispatch_enroll(payload, backend=backend)
    else:
        status, body = dispatch_heartbeat(payload, headers=self.headers, backend=backend)
    self.send_json(status, body)


legacy.DashboardHandler.do_GET = integrated_get
legacy.DashboardHandler.do_POST = integrated_post


def run():
    legacy.run()


if __name__ == "__main__":
    run()
