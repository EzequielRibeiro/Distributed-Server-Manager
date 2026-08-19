#!/usr/bin/env python3
"""Dedicated customer authentication API surface for Capivara DSM."""
from __future__ import annotations

from typing import Any

from customer_account_api import member_capabilities, require_customer
from customer_team_repository import CustomerTeamRepository

CUSTOMER_AUTH_PATHS = {"/api/customer/auth/me"}


def customer_auth_me(user: dict[str, Any] | None, backend) -> dict[str, Any]:
    username, customer_id = require_customer(user)
    repository = CustomerTeamRepository(backend)
    account_role = repository.account_role(customer_id, username)
    if account_role is None:
        raise PermissionError("customer account membership is required")
    return {
        "authenticated": True,
        "username": username,
        "role": "customer",
        "customer_id": customer_id,
        "scope_id": customer_id,
        "account": member_capabilities(account_role),
    }


def dispatch_customer_auth(
    method: str,
    path: str,
    *,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    if path not in CUSTOMER_AUTH_PATHS:
        return None
    if method != "GET":
        return 405, {"error": "method not allowed"}
    try:
        return 200, customer_auth_me(user, backend)
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except Exception:
        return 500, {"error": "customer authentication operation failed"}
