#!/usr/bin/env python3
"""Administrative API for Customer lifecycle, credentials and contracts."""
from __future__ import annotations

from typing import Any
from pathlib import Path

from customer_admin_repository import CustomerAdminRepository
from customer_mailer import send_temporary_password
from catalog_resource_profiles_http import catalog_resource_profiles

ROOT = Path(__file__).resolve().parents[1]

CUSTOMER_ADMIN_COLLECTION = "/api/admin/customers"
CUSTOMER_ADMIN_DETAIL = "/api/admin/customer"
CUSTOMER_ADMIN_PASSWORD_RESET = "/api/admin/customer/password-reset"
CUSTOMER_ADMIN_CONTRACT = "/api/admin/customer/contracts"
CUSTOMER_ADMIN_MEMBER_ROLE = "/api/admin/customer/member-role"
CUSTOMER_ADMIN_ACCESS = "/api/admin/customer/access"
CUSTOMER_PASSWORD_CHANGE = "/api/customer/password/change-temporary"
CUSTOMER_ADMIN_GET_PATHS = {CUSTOMER_ADMIN_COLLECTION, CUSTOMER_ADMIN_DETAIL}
CUSTOMER_ADMIN_POST_PATHS = {
    CUSTOMER_ADMIN_COLLECTION,
    CUSTOMER_ADMIN_PASSWORD_RESET,
    CUSTOMER_ADMIN_CONTRACT,
    CUSTOMER_ADMIN_MEMBER_ROLE,
    CUSTOMER_ADMIN_ACCESS,
    CUSTOMER_PASSWORD_CHANGE,
}


def _role(user: dict[str, Any] | None) -> str:
    return str((user or {}).get("role") or "")


def _admin_read(user: dict[str, Any] | None) -> bool:
    return _role(user) in {"admin", "controller", "operator"}


def _admin_write(user: dict[str, Any] | None) -> bool:
    return _role(user) in {"admin", "controller"}


def _deliver_temporary_password(email: str | None, username: str, password: str, *, reset: bool) -> bool:
    if not email:
        return False
    try:
        return bool(send_temporary_password(email, username, password, reset=reset))
    except Exception:
        # Credential creation/reset remains authoritative even if SMTP is
        # temporarily unavailable. The administrator receives the password once.
        return False


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

        contract_operator = path == CUSTOMER_ADMIN_CONTRACT and _role(user) == "operator"
        if not _admin_write(user) and not contract_operator:
            return 403, {"error": "administrative write access required"}

        if path == CUSTOMER_ADMIN_COLLECTION:
            email = str(payload.get("email") or "").strip() or None
            result = repository.create_customer(
                customer_id=str(payload.get("id") or ""),
                name=str(payload.get("name") or ""),
                username=str(payload.get("username") or ""),
                email=email,
                phone=(str(payload.get("phone") or "").strip() or None),
                controller_id=(str(payload.get("controller_id") or "").strip() or None),
            )
            result["delivered"] = _deliver_temporary_password(
                email,
                str(result["username"]),
                str(result["temporary_password"]),
                reset=False,
            )
            return 201, result

        if path == CUSTOMER_ADMIN_PASSWORD_RESET:
            username = str(payload.get("username") or "")
            matches = repository.search(username)
            email = None
            for customer in matches:
                if any(str(member.get("username")) == username.lower() for member in customer.get("users", [])):
                    email = customer.get("email")
                    break
            result = repository.reset_password(username)
            result["delivered"] = _deliver_temporary_password(
                email,
                str(result["username"]),
                str(result["temporary_password"]),
                reset=True,
            )
            return 200, result

        if path == CUSTOMER_ADMIN_CONTRACT:
            limit = int(payload.get("instance_limit") or 1)
            game_id = str(payload.get("game_id") or "").strip().lower()
            resource_profile_id = str(payload.get("resource_profile_id") or "").strip().lower()
            profiles = catalog_resource_profiles(ROOT, game_id).get("profiles", [])
            profile = next((item for item in profiles if str(item.get("id")) == resource_profile_id), None)
            if profile is None:
                raise ValueError("select a valid resource profile for this game")
            result = repository.create_contract(
                customer_id=str(payload.get("customer_id") or ""),
                game_id=game_id,
                instance_limit=limit,
                contract_id=(str(payload.get("id") or "").strip() or None),
                ends_at=(str(payload.get("ends_at") or "").strip() or None),
                resource_profile_id=resource_profile_id,
            )
            return 201, result

        if path == CUSTOMER_ADMIN_MEMBER_ROLE:
            repository.set_member_role(
                str(payload.get("customer_id") or ""),
                str(payload.get("username") or ""),
                str(payload.get("account_role") or ""),
            )
            return 200, {"updated": True}

        if path == CUSTOMER_ADMIN_ACCESS:
            profile = str(payload.get("permission_profile") or "").strip() or None
            repository.set_instance_access(
                str(payload.get("customer_id") or ""),
                str(payload.get("username") or ""),
                str(payload.get("instance_id") or ""),
                profile,
            )
            return 200, {"updated": True}
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
