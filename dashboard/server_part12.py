#!/usr/bin/env python3
"""Phase 14/15 HTTP integration for Agent installation and location UI."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import server_part11 as integration
from agent_installation_http import (
    AGENT_INSTALLATIONS_PATH,
    AGENT_INSTALLATION_STATUS_PATH,
    AGENT_RELEASES_PATH,
    dispatch_agent_installation_get,
    dispatch_agent_installation_post,
)

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_previous_post = legacy.DashboardHandler.do_POST
_authenticate = integration.integration.integrated_customer_authenticate
legacy.STATIC_FILES["/agent-installation.js"] = legacy.WEB_DIR / "agent-installation.js"
legacy.STATIC_FILES["/agent-location-ui.js"] = legacy.WEB_DIR / "agent-location-ui.js"


def _user(self):
    user = _authenticate(self.headers)
    if user is None:
        self.unauthorized()
    return user


def integrated_get(self):
    parsed = urlparse(self.path)
    if parsed.path not in {AGENT_INSTALLATION_STATUS_PATH, AGENT_RELEASES_PATH}:
        return _previous_get(self)
    user = _user(self)
    if user is None:
        return
    query = parse_qs(parsed.query)
    include_prereleases = str((query.get("include_prereleases") or ["0"])[0]).lower() in {
        "1", "true", "yes", "on"
    }
    result = dispatch_agent_installation_get(
        parsed.path,
        user=user,
        backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
        installation_id=(query.get("installation_id") or [None])[0],
        platform=(query.get("platform") or [None])[0],
        include_prereleases=include_prereleases,
    )
    status, body = result
    self.send_json(status, body)


def integrated_post(self):
    parsed = urlparse(self.path)
    if parsed.path != AGENT_INSTALLATIONS_PATH:
        return _previous_post(self)
    user = _user(self)
    if user is None:
        return
    try:
        payload = self.read_json_body()
    except ValueError:
        self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."})
        return
    result = dispatch_agent_installation_post(
        parsed.path,
        payload,
        user=user,
        backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
    )
    status, body = result
    self.send_json(status, body)


legacy.DashboardHandler.do_GET = integrated_get
legacy.DashboardHandler.do_POST = integrated_post


def run():
    legacy.run()


if __name__ == "__main__":
    run()
