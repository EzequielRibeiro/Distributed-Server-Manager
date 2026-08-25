#!/usr/bin/env python3
"""Transport-neutral Customer self-service API logic."""
from __future__ import annotations

from typing import Any, Callable

from customer_account_service import may_manage_members, normalize_registration, permissions_for
from customer_reference import resolve_customer_reference


def require_customer(user: dict[str, Any] | None) -> tuple[str, int]:
    if not user or user.get("role") != "customer":
        raise PermissionError("customer authentication required")
    raw_id = user.get("customer_id")
    if raw_id is not None:
        customer_id = resolve_customer_reference(raw_id)
    else:
        raw_code = user.get("customer_code") or user.get("scope_id")
        if not raw_code:
            raise PermissionError("customer authentication required")
        customer_id = resolve_customer_reference(raw_code, public_only=True)
    return str(user["username"]), customer_id


def member_capabilities(account_role: str) -> dict[str, Any]:
    return {
        "account_role": account_role,
        "permissions": sorted(permissions_for(account_role)),
        "may_manage_members": may_manage_members(account_role),
    }


def registration_payload(
    payload: dict[str, Any], normalize_email: Callable[[str], str]
) -> dict[str, str]:
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
