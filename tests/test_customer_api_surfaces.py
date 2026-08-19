#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
sys.path.insert(0, str(ROOT / "database"))

from customer_auth_api import CUSTOMER_AUTH_PATHS, dispatch_customer_auth
from customer_team_api import CUSTOMER_TEAM_PATHS
from customer_account_http import AUTHENTICATED_PATHS, PUBLIC_PATHS


def test_customer_auth_api_is_separate_from_admin_auth():
    assert "/api/customer/auth/me" in CUSTOMER_AUTH_PATHS
    assert "/api/auth/me" not in CUSTOMER_AUTH_PATHS
    assert "/api/customer/auth/me" not in AUTHENTICATED_PATHS


def test_customer_team_api_has_explicit_permission_operations():
    expected = {
        "/api/customer/team",
        "/api/customer/team/members/create",
        "/api/customer/team/members/role",
        "/api/customer/team/members/remove",
        "/api/customer/team/access",
    }
    assert expected <= CUSTOMER_TEAM_PATHS
    assert not (expected & AUTHENTICATED_PATHS)


def test_public_account_flows_remain_separate_from_team_api():
    assert "/api/customer/register" in PUBLIC_PATHS
    assert not (PUBLIC_PATHS & CUSTOMER_TEAM_PATHS)
    assert not (PUBLIC_PATHS & CUSTOMER_AUTH_PATHS)


def test_customer_auth_rejects_non_customer_before_repository_access():
    status, body = dispatch_customer_auth(
        "GET",
        "/api/customer/auth/me",
        user={"username": "admin", "role": "admin", "scope_id": None},
        backend=None,
    )
    assert status == 403
    assert "error" in body
