#!/usr/bin/env python3
"""Administrative Customer profile editing with immutable identity boundaries."""
from __future__ import annotations

from typing import Any

from admin_management_repository import AdminManagementRepository
from customer_billing import normalize_billing_identity
from customer_management_repository import CustomerManagementRepository
from customer_reference import resolve_customer_reference

_EDITABLE_FIELDS = {
    "name",
    "legal_name",
    "phone",
    "document_type",
    "document_number",
    "status",
    "registration_status",
    "controller_id",
    "billing_provider",
    "billing_customer_id",
    "billing_status",
}
_IMMUTABLE_FIELDS = {
    "id",
    "customer_id",
    "customer_code",
    "email",
    "account_email",
    "username",
    "email_verified_at",
    "sftp_username",
    "created_at",
}
_STATUS_VALUES = {"active", "inactive", "suspended", "disabled"}
_REGISTRATION_VALUES = {"pending", "active", "suspended", "cancelled"}


class CustomerProfileAdminRepository:
    """Update the administrative profile without changing login/public identity."""

    def __init__(self, backend):
        self.backend = backend
        self.admin = AdminManagementRepository(backend)
        self.management = CustomerManagementRepository(backend)
        self.dialect = self.management.dialect

    def initialize(self) -> None:
        self.backend.initialize()

    @staticmethod
    def _pk(reference: Any) -> int:
        return resolve_customer_reference(reference, public_only=isinstance(reference, str))

    @staticmethod
    def _clean_optional(value: Any, *, limit: int = 255) -> str | None:
        text = str(value or "").strip()
        if len(text) > limit:
            raise ValueError("customer profile field is too long")
        return text or None

    def update(self, customer_reference: Any, changes: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        if not isinstance(changes, dict):
            raise ValueError("customer profile changes must be an object")
        forbidden = sorted(key for key in changes if key in _IMMUTABLE_FIELDS)
        if forbidden:
            raise ValueError("immutable customer fields cannot be changed: " + ", ".join(forbidden))
        unknown = sorted(key for key in changes if key not in _EDITABLE_FIELDS)
        if unknown:
            raise ValueError("unsupported customer profile fields: " + ", ".join(unknown))
        if not changes:
            raise ValueError("at least one customer profile field is required")

        customer_id = self._pk(customer_reference)
        current = self.management.detail(customer_id)["customer"]
        normalized: dict[str, Any] = {}

        if "name" in changes:
            name = str(changes.get("name") or "").strip()
            if not name:
                raise ValueError("customer name is required")
            if len(name) > 255:
                raise ValueError("customer name is too long")
            normalized["name"] = name
        if "legal_name" in changes:
            normalized["legal_name"] = self._clean_optional(changes.get("legal_name"))
        if "phone" in changes:
            normalized["phone"] = self._clean_optional(changes.get("phone"), limit=64)

        if "document_type" in changes or "document_number" in changes:
            kind = changes.get("document_type", current.get("document_type"))
            number = changes.get("document_number", current.get("document_number"))
            kind, number = self.management._document(kind, number)
            normalized["document_type"] = kind
            normalized["document_number"] = number

        if "status" in changes:
            status = str(changes.get("status") or "").strip().lower()
            if status not in _STATUS_VALUES:
                raise ValueError("invalid customer status")
            normalized["status"] = status
        if "registration_status" in changes:
            status = str(changes.get("registration_status") or "").strip().lower()
            if status not in _REGISTRATION_VALUES:
                raise ValueError("invalid customer registration_status")
            normalized["registration_status"] = status

        if "controller_id" in changes:
            controller_id = str(changes.get("controller_id") or "").strip()
            if not controller_id:
                raise ValueError("controller_id is required")
            with self.admin.session() as session:
                controller = self.admin._resolve_controller(session, controller_id)
            normalized["controller_id"] = str(controller["id"])

        billing_keys = {"billing_provider", "billing_customer_id", "billing_status"}
        if billing_keys.intersection(changes):
            billing = normalize_billing_identity(
                provider=changes.get("billing_provider", current.get("billing_provider")),
                customer_id=changes.get("billing_customer_id", current.get("billing_customer_id")),
                status=changes.get("billing_status", current.get("billing_status")),
            )
            normalized.update(
                billing_provider=billing.provider,
                billing_customer_id=billing.customer_id,
                billing_status=billing.status,
            )

        changed = {
            key: value for key, value in normalized.items()
            if current.get(key) != value
        }
        if not changed:
            return {
                "updated": False,
                "customer_id": customer_id,
                "customer_code": current["customer_code"],
                "changed_fields": [],
                "before": {},
                "after": {},
                "customer": current,
            }

        ph = self.dialect.placeholder
        assignments = [f"{key}={ph}" for key in changed]
        assignments.append("updated_at=CURRENT_TIMESTAMP")
        params = tuple(changed[key] for key in changed) + (customer_id,)
        with self.admin.session(transaction=True) as session:
            if "billing_provider" in changed or "billing_customer_id" in changed:
                provider = changed.get("billing_provider", current.get("billing_provider"))
                billing_id = changed.get("billing_customer_id", current.get("billing_customer_id"))
                if provider and billing_id:
                    duplicate = session.execute(
                        f"SELECT id FROM customers WHERE billing_provider={ph} AND billing_customer_id={ph} AND id<>{ph}",
                        (provider, billing_id, customer_id),
                    ).fetchone()
                    if duplicate is not None:
                        raise ValueError("billing customer already linked")
            session.execute(
                "UPDATE customers SET " + ",".join(assignments) + f" WHERE id={ph}",
                params,
            )

        after = self.management.detail(customer_id)["customer"]
        return {
            "updated": True,
            "customer_id": customer_id,
            "customer_code": str(after["customer_code"]),
            "changed_fields": sorted(changed),
            "before": {key: current.get(key) for key in changed},
            "after": {key: after.get(key) for key in changed},
            "customer": after,
        }


__all__ = ["CustomerProfileAdminRepository"]
