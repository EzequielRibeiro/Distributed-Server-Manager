#!/usr/bin/env python3
"""Phase 21 integration: Universal Event Platform timeline API."""

from __future__ import annotations

from urllib.parse import urlparse

import server_part13 as integration
from timeline_http import TIMELINE_PATH, dispatch_timeline_get

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_authenticate = integration._authenticate


def _backend():
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def integrated_get(self):
    parsed = urlparse(self.path)
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
