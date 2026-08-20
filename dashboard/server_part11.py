#!/usr/bin/env python3
"""Phase 8 integration: make Customer browser assets session-aware."""

from __future__ import annotations

import server_part10 as integration
from controller_session import session_user_from_headers
from customer_session_auth import authenticate_browser_customer


legacy = integration.legacy
part8 = integration.integration.integration
_previous_authenticate = part8.integrated_authenticate


def integrated_authenticate(headers):
    return authenticate_browser_customer(
        headers,
        session_authenticator=session_user_from_headers,
        fallback_authenticator=_previous_authenticate,
    )


# server_part8 resolves integrated_authenticate from its module globals when a
# request is handled, so replacing the module attribute fixes its protected
# Customer asset route without duplicating the route or growing server.py.
part8.integrated_authenticate = integrated_authenticate
legacy.authenticate = integrated_authenticate


def run():
    legacy.run()


if __name__ == "__main__":
    run()
