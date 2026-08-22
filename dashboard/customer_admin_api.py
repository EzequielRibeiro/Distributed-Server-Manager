#!/usr/bin/env python3
"""Administrative API for Customer lifecycle, credentials and contracts."""
from __future__ import annotations

from typing import Any

from customer_admin_repository import CustomerAdminRepository

CUSTOMER_ADMIN_COLLECTION = "/api/admin/customers"
CUSTOMER_ADMIN_DETAIL = "/api/admin/customer"
CUSTOMER_ADMIN_PASSWORD_RESET = "/api/admin/customer/password-reset"
CUSTOMER_ADMIN_CONTRACT = "/api/admin/customer/contracts"
CUSTOMER_PASSWORD_CHANGE = "/api/customer/password/change-temporary"
CUSTOMER_ADMIN_GET_PATHS = {CUSTOMER_ADMIN_COLLECTION, CUSTOMER_ADMIN_DETAIL}
CUSTOMER_ADMIN_POST_PATHS = {
    CUSTOMER_ADMIN_COLLECTION,
    CUSTOMER_ADMIN_PASSWORD_RESET,
    CUSTOMER_ADMIN_CONTRACT,
    CUSTOMER_PASSWORD_CHANGE,
}


def _role(user: dict[str, Any] | None) -> str:
    return str((user or {}).get("role") or "")


def _admin_read(user: dict[str, Any] | None) -> bool:
    return _role(user) in {"admin", "controller", "operator"}


def _admin_write(user: dict[str, Any] | None) -> bool:
    return _role(user) in {"admin", "controller"}


def dispatch_customer_admin_get(path: str, query: dict[str, list[str]], *, user, backend):
    if path not in CUSTOMER_ADMIN_GET_PATHS:
        return None
    if not _admin_read(user):
        return 403, {"error": "access denied"}
    try:
        repository = CustomerAdminRepository(backend)
        if path == CUSTOMER_ADMIN_COLLECTION:
            term = str((query.get("q") or [""])[0])
            return 200, {"customers": repository.search(term)}
        customer_id = str((query.get("id") or [""])[0]).strip()
        if not customer_id:
            return 400, {"error": "customer id is required"}
        return 200, repository.detail(customer_id)
    except ValueError as exc:
        return 404, {"error": str(exc)}
    except Exception:
        return 500, {"error": "customer administration query failed"}


def dispatch_customer_admin_post(path: str, payload: dict[str, Any], *, user, backend):
    if path not in CUSTOMER_ADMIN_POST_PATHS:
        return None
    repository = CustomerAdminRepository(backend)
    try:
        if path == CUSTOMER_PASSWORD_CHANGE:
            if _role(user) != "customer":
                return 403, {"error": "access denied"}
            password = str(payload.get("password") or "")
            confirmation = str(payload.get("password_confirmation") or "")
            if password != confirmation:
                return 400, {"error": "password confirmation does not match"}
            repository.change_temporary_password(str(user.get("username") or ""), password)
            return 200, {"changed": True, "must_change_password": False}

        if not _admin_write(user):
            return 403, {"error": "administrative write access required"}

        if path == CUSTOMER_ADMIN_COLLECTION:
            result = repository.create_customer(
                customer_id=str(payload.get("id") or ""),
                name=str(payload.get("name") or ""),
                username=str(payload.get("username") or ""),
                email=(str(payload.get("email") or "").strip() or None),
                phone=(str(payload.get("phone") or "").strip() or None),
                controller_id=(str(payload.get("controller_id") or "").strip() or None),
            )
            return 201, result

        if path == CUSTOMER_ADMIN_PASSWORD_RESET:
            return 200, repository.reset_password(str(payload.get("username") or ""))

        if path == CUSTOMER_ADMIN_CONTRACT:
            limit = int(payload.get("instance_limit") or 1)
            result = repository.create_contract(
                customer_id=str(payload.get("customer_id") or ""),
                game_id=str(payload.get("game_id") or ""),
                instance_limit=limit,
                contract_id=(str(payload.get("id") or "").strip() or None),
                ends_at=(str(payload.get("ends_at") or "").strip() or None),
            )
            return 201, result
    except (ValueError, TypeError) as exc:
        return 400, {"error": str(exc)}
    except Exception:
        return 500, {"error": "customer administration operation failed"}
    return 404, {"error": "not found"}


__all__ = [
    "CUSTOMER_ADMIN_GET_PATHS", "CUSTOMER_ADMIN_POST_PATHS",
    "CUSTOMER_PASSWORD_CHANGE", "dispatch_customer_admin_get",
    "dispatch_customer_admin_post",
]
