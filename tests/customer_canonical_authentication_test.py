#!/usr/bin/env python3

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"

if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from login_credentials import authenticate_login_credentials


def canonical_customer():
    return {
        "username": "aurora",
        "role": "customer",
        "customer_id": 1,
        "customer_code": "CLI-000001",
        "scope_id": 1,
        "active": True,
    }


def test_customer_legacy_identity_is_not_accepted_as_login_identity():
    def legacy_authenticator(_headers):
        return {
            "username": "aurora",
            "role": "customer",
            "scope_id": 1,
        }

    def customer_authenticator(_headers):
        return canonical_customer()

    user = authenticate_login_credentials(
        {"Authorization": "Basic test"},
        controller_authenticator=legacy_authenticator,
        customer_authenticator=customer_authenticator,
    )

    assert user == canonical_customer()
    assert user["customer_id"] == 1
    assert user["customer_code"] == "CLI-000001"


def test_system_identity_still_uses_controller_authenticator():
    expected = {
        "username": "admin",
        "role": "admin",
        "scope_id": None,
    }

    customer_called = False

    def controller_authenticator(_headers):
        return expected

    def customer_authenticator(_headers):
        nonlocal customer_called
        customer_called = True
        return canonical_customer()

    user = authenticate_login_credentials(
        {"Authorization": "Basic test"},
        controller_authenticator=controller_authenticator,
        customer_authenticator=customer_authenticator,
    )

    assert user == expected
    assert customer_called is False


def test_invalid_customer_does_not_fall_back_to_legacy_customer_identity():
    legacy = {
        "username": "aurora",
        "role": "customer",
        "scope_id": 1,
    }

    user = authenticate_login_credentials(
        {"Authorization": "Basic test"},
        controller_authenticator=lambda _headers: legacy,
        customer_authenticator=lambda _headers: None,
    )

    assert user is None
