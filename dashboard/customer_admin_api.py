#!/usr/bin/env python3
"""Administrative API for separated Customer management workflows."""
from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from activity_audit_repository import ActivityAuditRepository
from activity_humanizer import actor_name, humanize
from core.catalog_resource_profile_policy import resolve_catalog_resource_profile
from customer_admin_repository import CustomerAdminRepository
from customer_mailer import send_temporary_password
from customer_management_repository import CustomerManagementRepository

ROOT = Path(__file__).resolve().parents[1]

CUSTOMER_ADMIN_COLLECTION = "/api/admin/customers"
CUSTOMER_ADMIN_OPTIONS = "/api/admin/customers/options"
CUSTOMER_ADMIN_DETAIL = "/api/admin/customer"
CUSTOMER_ADMIN_PASSWORD_RESET = "/api/admin/customer/password-reset"
CUSTOMER_ADMIN_CONTRACT = "/api/admin/customer/contracts"
CUSTOMER_ADMIN_MEMBER_ROLE = "/api/admin/customer/member-role"
CUSTOMER_ADMIN_ACCESS = "/api/admin/customer/access"
CUSTOMER_PASSWORD_CHANGE = "/api/customer/password/change-temporary"
CUSTOMER_ADMIN_GET_PATHS = {
    CUSTOMER_ADMIN_COLLECTION,
    CUSTOMER_ADMIN_OPTIONS,
    CUSTOMER_ADMIN_DETAIL,
}
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


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _deliver_temporary_password(email: str | None, username: str, password: str, *, reset: bool) -> bool:
    if not email:
        return False
    try:
        return bool(send_temporary_password(email, username, password, reset=reset))
    except Exception:
        return False


def _customer_code(payload: dict[str, Any], *, required: bool = True) -> str | None:
    value = str(payload.get("customer_code") or "").strip().upper()
    if not value:
        if required:
            raise ValueError("customer_code is required")
        return None
    return value


def _audit(
    backend,
    user,
    *,
    action: str,
    category: str,
    target_type: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    changes: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    actor_id = str((user or {}).get("username") or (user or {}).get("id") or "").strip() or None
    ActivityAuditRepository(backend).record_action(
        actor_id=actor_id,
        actor_name=actor_name(user),
        actor_role=str((user or {}).get("role") or "").strip() or None,
        action=action,
        category=category,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        result="success",
        summary=humanize(action, user=user, target_name=target_name, changes=changes, context=context),
        changes=changes,
    )


def _member_role(detail: dict[str, Any], username: str) -> str | None:
    for member in detail.get("users", []):
        if str(member.get("username") or "") == username:
            return str(member.get("account_role") or "") or None
    return None


def _instance_access(detail: dict[str, Any], username: str, instance_id: str) -> str | None:
    for member in detail.get("users", []):
        if str(member.get("username") or "") == username:
            return (member.get("instance_access") or {}).get(instance_id)
    return None


def dispatch_customer_admin_get(path: str, query: dict[str, list[str]], *, user, backend):
    if path not in CUSTOMER_ADMIN_GET_PATHS:
        return None
    if not _admin_read(user):
        return 403, {"error": "access denied"}
    try:
        repository = CustomerManagementRepository(backend)
        if path == CUSTOMER_ADMIN_OPTIONS:
            return 200, _json_safe(repository.creation_options())
        if path == CUSTOMER_ADMIN_COLLECTION:
            term = str((query.get("q") or [""])[0])
            field = str((query.get("field") or ["all"])[0])
            return 200, _json_safe({"customers": repository.search(term, field)})
        customer_code = str((query.get("customer_code") or [""])[0]).strip().upper()
        if not customer_code:
            return 400, {"error": "customer_code is required"}
        return 200, _json_safe(repository.detail(customer_code))
    except ValueError as exc:
        status = 404 if path == CUSTOMER_ADMIN_DETAIL else 400
        return status, {"error": str(exc)}
    except Exception:
        return 500, {"error": "customer administration query failed"}


def dispatch_customer_admin_post(path: str, payload: dict[str, Any], *, user, backend):
    if path not in CUSTOMER_ADMIN_POST_PATHS:
        return None

    password_repository = CustomerAdminRepository(backend)
    management = CustomerManagementRepository(backend)
    try:
        if path == CUSTOMER_PASSWORD_CHANGE:
            if _role(user) != "customer":
                return 403, {"error": "access denied"}
            password = str(payload.get("password") or "")
            confirmation = str(payload.get("password_confirmation") or "")
            if password != confirmation:
                return 400, {"error": "password confirmation does not match"}
            username = str(user.get("username") or "")
            password_repository.change_temporary_password(username, password)
            _audit(
                backend,
                user,
                action="customer.password_changed",
                category="authentication",
                target_type="customer_user",
                target_id=username,
                target_name=username,
                changes={"password": {"changed": True}},
            )
            return 200, {"changed": True, "must_change_password": False}

        contract_operator = path == CUSTOMER_ADMIN_CONTRACT and _role(user) == "operator"
        if not _admin_write(user) and not contract_operator:
            return 403, {"error": "administrative write access required"}

        if path == CUSTOMER_ADMIN_COLLECTION:
            if str(payload.get("id") or payload.get("customer_id") or "").strip():
                raise ValueError("customer id is generated automatically; do not supply id/customer_id")
            email = str(payload.get("email") or "").strip()
            result = management.create_account(
                name=str(payload.get("name") or ""),
                legal_name=(str(payload.get("legal_name") or "").strip() or None),
                document_type=str(payload.get("document_type") or ""),
                document_number=str(payload.get("document_number") or ""),
                username=str(payload.get("username") or ""),
                email=email,
                phone=(str(payload.get("phone") or "").strip() or None),
                controller_id=(str(payload.get("controller_id") or "").strip() or None),
                billing_provider=(str(payload.get("billing_provider") or "").strip() or None),
                billing_customer_id=(str(payload.get("billing_customer_id") or "").strip() or None),
                billing_status=(str(payload.get("billing_status") or "").strip() or None),
            )
            result["delivered"] = _deliver_temporary_password(email, str(result["username"]), str(result["temporary_password"]), reset=False)
            customer_name = str(result.get("name") or payload.get("name") or result.get("customer_code") or "cliente")
            _audit(
                backend,
                user,
                action="customer.created",
                category="customers",
                target_type="customer",
                target_id=str(result.get("customer_code") or result.get("id") or "") or None,
                target_name=customer_name,
            )
            return 201, _json_safe(result)

        if path == CUSTOMER_ADMIN_PASSWORD_RESET:
            username = str(payload.get("username") or "").strip().lower()
            matches = management.search(username, "username")
            email = None
            customer_name = username
            for customer in matches:
                if any(str(member.get("username")) == username for member in customer.get("users", [])):
                    email = customer.get("email")
                    customer_name = str(customer.get("name") or username)
                    break
            result = password_repository.reset_password(username)
            result["delivered"] = _deliver_temporary_password(email, str(result["username"]), str(result["temporary_password"]), reset=True)
            _audit(
                backend,
                user,
                action="customer.password_reset",
                category="customers",
                target_type="customer_user",
                target_id=username,
                target_name=customer_name,
                changes={"password": {"changed": True}},
            )
            return 200, _json_safe(result)

        if path == CUSTOMER_ADMIN_CONTRACT:
            customer_code = _customer_code(payload)
            detail = management.detail(customer_code)
            customer_name = str((detail.get("customer") or {}).get("name") or customer_code)
            limit = int(payload.get("instance_limit") or 1)
            game_id = str(payload.get("game_id") or "").strip().lower()
            requested_profile_id = str(payload.get("resource_profile_id") or "").strip().lower()
            resource_profile_id, _profile, _profile_catalog = resolve_catalog_resource_profile(
                root=ROOT,
                game_id=game_id,
                requested_profile_id=requested_profile_id or None,
                require_catalog=True,
            )
            resource_profile_source = "selected" if requested_profile_id else "game_default"
            result = management.create_contract(
                customer_code=customer_code,
                game_id=game_id,
                instance_limit=limit,
                ends_at=(str(payload.get("ends_at") or "").strip() or None),
                resource_profile_id=resource_profile_id,
                resource_profile_source=resource_profile_source,
            )
            _audit(
                backend,
                user,
                action="customer.contract.created",
                category="contracts",
                target_type="customer",
                target_id=customer_code,
                target_name=customer_name,
                context={"game_id": game_id},
            )
            return 201, _json_safe(result)

        if path == CUSTOMER_ADMIN_MEMBER_ROLE:
            customer_code = _customer_code(payload)
            username = str(payload.get("username") or "").strip().lower()
            new_role = str(payload.get("account_role") or "").strip().lower()
            before = management.detail(customer_code)
            old_role = _member_role(before, username)
            password_repository.set_member_role(customer_code, username, new_role)
            _audit(
                backend,
                user,
                action="customer.member_role.updated",
                category="customers",
                target_type="customer_user",
                target_id=username,
                target_name=username,
                changes={"account_role": {"before": old_role, "after": new_role}},
                context={"customer_code": customer_code},
            )
            return 200, {"updated": True}

        if path == CUSTOMER_ADMIN_ACCESS:
            customer_code = _customer_code(payload)
            username = str(payload.get("username") or "").strip().lower()
            instance_id = str(payload.get("instance_id") or "").strip()
            profile = str(payload.get("permission_profile") or "").strip() or None
            before = management.detail(customer_code)
            old_profile = _instance_access(before, username, instance_id)
            password_repository.set_instance_access(customer_code, username, instance_id, profile)
            instance_name = instance_id
            for instance in before.get("instances", []):
                if str(instance.get("id") or "") == instance_id:
                    instance_name = str(instance.get("name") or instance_id)
                    break
            _audit(
                backend,
                user,
                action="customer.instance_access.updated",
                category="customers",
                target_type="customer_user",
                target_id=username,
                target_name=username,
                changes={"permission_profile": {"before": old_profile, "after": profile}},
                context={"instance_id": instance_id, "instance_name": instance_name},
            )
            return 200, {"updated": True}
    except (ValueError, TypeError) as exc:
        return 400, {"error": str(exc)}
    except Exception:
        return 500, {"error": "customer administration operation failed"}
    return 404, {"error": "not found"}


__all__ = [
    "CUSTOMER_ADMIN_GET_PATHS",
    "CUSTOMER_ADMIN_POST_PATHS",
    "CUSTOMER_PASSWORD_CHANGE",
    "dispatch_customer_admin_get",
    "dispatch_customer_admin_post",
]
