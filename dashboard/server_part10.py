#!/usr/bin/env python3
"""Phase 7/8 HTTP integration for wizard readiness and Customer sessions."""

from __future__ import annotations

from urllib.parse import urlparse

import server_part9 as integration
from controller_session import session_user_from_headers
from customer_session_auth import authenticate_browser_customer
from placement_readiness_http import (
    PLACEMENT_READINESS_PATH,
    dispatch_placement_readiness_get,
)

legacy = integration.legacy
part8 = integration.integration
_previous_get = legacy.DashboardHandler.do_GET
_previous_customer_authenticate = part8.integrated_authenticate
legacy.STATIC_FILES["/create-server-wizard.js"] = legacy.WEB_DIR / "create-server-wizard.js"
legacy.STATIC_FILES["/create-server-wizard.css"] = legacy.WEB_DIR / "create-server-wizard.css"


def integrated_customer_authenticate(headers):
    """Recognize the same cookie session used by protected Customer pages."""
    return authenticate_browser_customer(
        headers,
        session_authenticator=session_user_from_headers,
        fallback_authenticator=_previous_customer_authenticate,
    )


# server_part8 resolves this module global at request time.  Updating it here
# makes injected/protected Customer assets use the established browser session
# while preserving header-based authentication as a compatibility fallback.
part8.integrated_authenticate = integrated_customer_authenticate
legacy.authenticate = integrated_customer_authenticate


def integrated_get(self):
    parsed = urlparse(self.path)
    if parsed.path != PLACEMENT_READINESS_PATH:
        return _previous_get(self)

    user = integrated_customer_authenticate(self.headers)
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
