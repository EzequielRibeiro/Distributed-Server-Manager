#!/usr/bin/env python3
"""Phase 11 HTTP integration for remote Linux Agents."""

from __future__ import annotations

from urllib.parse import urlparse

import server_part10 as integration
from agent_remote_http import ENROLL_PATH, HEARTBEAT_PATH, dispatch_enroll, dispatch_heartbeat

legacy = integration.legacy
_previous_post = legacy.DashboardHandler.do_POST


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


legacy.DashboardHandler.do_POST = integrated_post


def run():
    legacy.run()


if __name__ == "__main__":
    run()
