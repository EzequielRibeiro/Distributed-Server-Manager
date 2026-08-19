#!/usr/bin/env python3
"""Transport-neutral customer self-service API logic.

HTTP routing remains a thin adapter in dashboard/server.py; business rules live here.
"""
from __future__ import annotations

from typing import Any, Callable

from customer_account_service import may_manage_members, normalize_registration, permissions_for


def require_customer(user: dict[str, Any] | None) -> tuple[str, str]:
    if not user or user.get("role") != "customer" or not user.get("scope_id"):
        raise PermissionError("customer authentication required")
    return str(user["username"]), str(user["scope_id"])


def member_capabilities(account_role: str) -> dict[str, Any]:
    return {
        "account_role": account_role,
        "permissions": sorted(permissions_for(account_role)),
        "may_manage_members": may_manage_members(account_role),
    }


def registration_payload(payload: dict[str, Any], normalize_email: Callable[[str], str]) -> dict[str, str]:
    request = normalize_registration(payload)
    password = str(payload.get("password", ""))
    if len(password) < 8:
        raise ValueError("password must have at least 8 characters")
    return {
        "name": request.name,
        "email": normalize_email(request.email),
        "phone": request.phone,
        "document_type": request.document_type,
        "document_number": request.document_number,
        "password": password,
    }


def require_member_management(actor_role: str) -> None:
    if not may_manage_members(actor_role):
        raise PermissionError("customer member management is not permitted")
