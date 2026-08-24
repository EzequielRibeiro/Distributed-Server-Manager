#!/usr/bin/env python3
"""Regression contracts for dashboard area isolation.

Controller HTML pages are application shells. Authentication credentials are
stored by the frontend and attached to API requests, so a normal browser
navigation to /index.html does not contain an Authorization header.

Security-sensitive data and operations remain protected by the API
authentication and authorization layer.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "dashboard" / "server_part8.py").read_text(
    encoding="utf-8"
)


def test_customer_pages_are_server_side_protected():
    assert (
        'CUSTOMER_PROTECTED_PAGES={'
        '"/customer.html","/customer-instance.html","/customer-members.html"}'
        in SOURCE
    )
    assert '_require_area_role(self,user,{"customer"})' in SOURCE


def test_controller_pages_are_application_shells():
    assert "CONTROLLER_PROTECTED_PAGES={" in SOURCE
    for page in (
        "/", "/index.html", "/console.html", "/settings.html",
        "/users.html", "/agents.html", "/contract-demo.html",
    ):
        assert f'"{page}"' in SOURCE
    assert "*CONTROLLER_DASHBOARD_FILES.keys()" in SOURCE

    assert "if path in CONTROLLER_PROTECTED_PAGES:" in SOURCE
    assert 'if path in {"/","/index.html"}:' in SOURCE
    assert "_serve_controller_page(self)" in SOURCE


def test_controller_shell_does_not_require_basic_auth_header():
    """Avoid login -> index -> login redirect loops.

    Browser navigation does not automatically copy the Basic Auth token from
    sessionStorage into the HTTP Authorization header.
    """

    start = SOURCE.index("if path in CONTROLLER_PROTECTED_PAGES:")
    end = SOURCE.index(
        'if path=="/api/instance/delete/backups":',
        start,
    )
    controller_block = SOURCE[start:end]

    assert "integrated_authenticate(self.headers)" not in controller_block
    assert "session_user_from_headers(self.headers)" in controller_block
    assert '_require_area_role(' in controller_block
    assert '{"admin","controller","operator"}' in controller_block
    assert 'self.send_header("Location","/login.html")' in controller_block


def test_customer_apis_reject_admin_controller_sessions():
    # Authenticated customer dispatches continue through customer-only gates.
    assert SOURCE.count(
        '_require_area_role(self,user,{"customer"})'
    ) >= 4


def test_sensitive_instance_api_still_authenticates():
    start = SOURCE.index('if path=="/api/instance/delete/backups":')
    end = SOURCE.index(
        'if path=="/api/instance/delete/backup":',
        start,
    )
    api_block = SOURCE[start:end]

    assert "integrated_authenticate(self.headers)" in api_block
    assert "self.unauthorized()" in api_block


def test_area_gate_distinguishes_unauthenticated_from_wrong_role():
    assert "handler.unauthorized();return False" in SOURCE
    assert "handler.forbidden();return False" in SOURCE
