#!/usr/bin/env python3
"""Customer self-service profile read/update HTTP composition."""
from __future__ import annotations

import uuid
from urllib.parse import urlparse

from alert_repository import AlertSession
from customer_audit import audit_customer_event
from customer_management_repository import CustomerManagementRepository
from customer_profile_admin_repository import CustomerProfileAdminRepository
from customer_reference import resolve_customer_reference
from universal_event_repository import UniversalEventRepository

CUSTOMER_PROFILE_PATH = "/api/customer/profile"
_EDITABLE = {"name", "legal_name", "phone", "document_type", "document_number"}
_PUBLIC = (
    "customer_code", "name", "legal_name", "phone", "document_type", "document_number",
    "account_email", "email_verified_at", "registration_status",
)


def _backend(legacy):
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _identity(user, backend):
    if not user or str(user.get("role") or "").strip().lower() != "customer" or not user.get("scope_id"):
        raise PermissionError("customer authentication required")
    customer_id = resolve_customer_reference(user["scope_id"], public_only=isinstance(user["scope_id"], str))
    customer = CustomerManagementRepository(backend).detail(customer_id)["customer"]
    username = str(user.get("username") or "").strip()
    ph = "?" if backend.name == "sqlite" else "%s"
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                (customer_id, username),
            ).fetchone()
        finally:
            session.close()
    account_role = str((row or {}).get("account_role") if hasattr(row, "get") else (row["account_role"] if row is not None else "") or "").lower()
    return customer_id, customer, username, account_role


def _public(customer, account_role):
    return {key: customer.get(key) for key in _PUBLIC} | {"account_role": account_role}


def customer_profile_get(*, user, backend):
    try:
        _, customer, _, account_role = _identity(user, backend)
        return 200, {"profile": _public(customer, account_role), "editable": account_role in {"owner", "manager"}}
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except Exception:
        return 500, {"error": "customer_profile_unavailable", "message": "Não foi possível consultar o perfil."}


def customer_profile_update(payload, *, user, backend):
    body = payload if isinstance(payload, dict) else {}
    changes = body.get("changes")
    correlation_id = str(body.get("correlation_id") or "").strip() or str(uuid.uuid4())
    if not isinstance(changes, dict) or not changes:
        return 400, {"error": "invalid_request", "message": "changes must be a non-empty object"}
    forbidden = sorted(set(changes) - _EDITABLE)
    if forbidden:
        return 400, {"error": "protected_fields", "message": "Campos protegidos não podem ser alterados: " + ", ".join(forbidden)}
    try:
        customer_id, customer, username, account_role = _identity(user, backend)
        if account_role not in {"owner", "manager"}:
            raise PermissionError("only Customer owner or manager can edit the profile")
        result = CustomerProfileAdminRepository(backend).update(customer_id, changes)
        audit_customer_event(
            backend,
            username=username,
            action="CUSTOMER_PROFILE_UPDATED",
            result="success",
            details={
                "actor": username,
                "role": "customer",
                "account_role": account_role,
                "customer_id": customer_id,
                "customer_code": customer.get("customer_code"),
                "correlation_id": correlation_id,
                "changed_fields": result["changed_fields"],
                "before": result["before"],
                "after": result["after"],
            },
        )
        if result["updated"]:
            try:
                UniversalEventRepository(backend).publish({
                    "event_type": "CUSTOMER_PROFILE_UPDATED",
                    "source": "dashboard.customer-self-service",
                    "source_id": str(customer.get("customer_code") or customer_id),
                    "severity": "info",
                    "correlation_id": correlation_id,
                    "actor_type": "customer",
                    "actor_id": username,
                    "data": {
                        "customer_id": str(customer_id),
                        "customer_code": customer.get("customer_code"),
                        "changed_fields": result["changed_fields"],
                    },
                })
            except Exception:
                pass
        return 200, {
            "updated": result["updated"],
            "changed_fields": result["changed_fields"],
            "profile": _public(result["customer"], account_role),
            "correlation_id": correlation_id,
        }
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "customer_profile_update_failed", "message": "Não foi possível atualizar o perfil."}


def install_customer_profile_self_service(legacy, authenticate):
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def do_get(self):
        if urlparse(self.path).path != CUSTOMER_PROFILE_PATH:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        status, payload = customer_profile_get(user=user, backend=_backend(legacy))
        self.send_json(status, payload)

    def do_post(self):
        if urlparse(self.path).path != CUSTOMER_PROFILE_PATH:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."}); return
        status, response = customer_profile_update(payload, user=user, backend=_backend(legacy))
        self.send_json(status, response)

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = ["CUSTOMER_PROFILE_PATH", "customer_profile_get", "customer_profile_update", "install_customer_profile_self_service"]
