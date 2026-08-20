#!/usr/bin/env python3
"""Phase 7 HTTP integration for create-server wizard readiness."""

from __future__ import annotations

from urllib.parse import urlparse

import server_part9 as integration
from placement_readiness_http import (
    PLACEMENT_READINESS_PATH,
    dispatch_placement_readiness_get,
)

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
legacy.STATIC_FILES["/create-server-wizard.js"] = legacy.WEB_DIR / "create-server-wizard.js"
legacy.STATIC_FILES["/create-server-wizard.css"] = legacy.WEB_DIR / "create-server-wizard.css"


def integrated_get(self):
    parsed = urlparse(self.path)
    if parsed.path != PLACEMENT_READINESS_PATH:
        return _previous_get(self)

    user = integration.integration.integrated_authenticate(self.headers)
    if user is None:
        self.unauthorized()
        return

    result = dispatch_placement_readiness_get(
        parsed.path,
        user=user,
        backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
    )
    status, body = result
    self.send_json(status, body)


legacy.DashboardHandler.do_GET = integrated_get


def run():
    legacy.run()


if __name__ == "__main__":
    run()
