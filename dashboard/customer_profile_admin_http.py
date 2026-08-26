#!/usr/bin/env python3
"""Administrative Customer profile editing HTTP composition."""
from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlparse

from customer_audit import audit_customer_event
from customer_management_repository import CustomerManagementRepository
from customer_profile_admin_repository import CustomerProfileAdminRepository
from universal_event_repository import UniversalEventRepository

CUSTOMER_PROFILE_UPDATE_PATH = "/api/admin/customer/profile"


def _backend(legacy):
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _role(user) -> str:
    return str((user or {}).get("role") or "").strip().lower()


def _actor(user) -> str:
    return str((user or {}).get("username") or "unknown").strip() or "unknown"


def _authorize(user, customer: dict) -> None:
    role = _role(user)
    if role == "admin":
        return
    if role == "controller" and str((user or {}).get("scope_id") or "") == str(customer.get("controller_id") or ""):
        return
    raise PermissionError("Customer administration access denied")


def _publish(backend, *, customer: dict, actor: str, role: str, correlation_id: str, before: dict, after: dict) -> None:
    try:
        UniversalEventRepository(backend).publish({
            "event_id": str(uuid.uuid4()),
            "schema_version": 1,
            "event_type": "CUSTOMER_PROFILE_UPDATED",
            "source": "dashboard.customer-admin",
            "source_id": str(customer.get("customer_code") or customer.get("id") or "customer"),
            "severity": "info",
            "correlation_id": correlation_id,
            "actor_type": "user",
            "actor_id": actor,
            "data": {
                "customer_id": customer.get("id"),
                "customer_code": customer.get("customer_code"),
                "role": role,
                "before": before,
                "after": after,
                "changed_fields": sorted(after),
            },
        })
    except Exception:
        pass


def update_customer_profile_for_user(payload: dict[str, Any] | None, *, user: dict[str, Any], backend) -> tuple[int, dict[str, Any]]:
    body = payload if isinstance(payload, dict) else {}
    customer_code = str(body.get("customer_code") or "").strip().upper()
    changes = body.get("changes")
    if not customer_code:
        return 400, {"error": "invalid_request", "message": "customer_code is required"}
    if not isinstance(changes, dict):
        return 400, {"error": "invalid_request", "message": "changes must be an object"}

    actor = _actor(user)
    role = _role(user)
    correlation_id = str(body.get("correlation_id") or "").strip() or str(uuid.uuid4())
    try:
        current = CustomerManagementRepository(backend).detail(customer_code)["customer"]
        _authorize(user, current)
        result = CustomerProfileAdminRepository(backend).update(customer_code, changes)
        audit_customer_event(
            backend,
            username=actor,
            action="CUSTOMER_PROFILE_UPDATED",
            result="success",
            details={
                "actor": actor,
                "role": role,
                "customer_id": result["customer_id"],
                "customer_code": result["customer_code"],
                "correlation_id": correlation_id,
                "changed_fields": result["changed_fields"],
                "before": result["before"],
                "after": result["after"],
            },
        )
        if result["updated"]:
            _publish(
                backend,
                customer=result["customer"],
                actor=actor,
                role=role,
                correlation_id=correlation_id,
                before=result["before"],
                after=result["after"],
            )
        return 200, {**result, "correlation_id": correlation_id}
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        try:
            audit_customer_event(
                backend,
                username=actor,
                action="CUSTOMER_PROFILE_UPDATED",
                result="rejected",
                details={
                    "actor": actor,
                    "role": role,
                    "customer_code": customer_code,
                    "correlation_id": correlation_id,
                    "reason": str(exc),
                },
            )
        except Exception:
            pass
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "customer_profile_update_failed", "message": "Falha ao atualizar o Customer."}


def install_customer_profile_administration(legacy, authenticate) -> None:
    """Install Customer profile update route without adding logic to server.py."""
    previous_post = legacy.DashboardHandler.do_POST

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path != CUSTOMER_PROFILE_UPDATE_PATH:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."})
            return
        status, response = update_customer_profile_for_user(payload, user=user, backend=_backend(legacy))
        self.send_json(status, response)

    legacy.DashboardHandler.do_POST = do_post


__all__ = [
    "CUSTOMER_PROFILE_UPDATE_PATH",
    "install_customer_profile_administration",
    "update_customer_profile_for_user",
]
