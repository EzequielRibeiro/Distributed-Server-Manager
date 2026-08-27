#!/usr/bin/env python3
"""Customer-impact health recording, correlation and safe UEP publication."""
from __future__ import annotations

import re
from typing import Any

from customer_health_repository import CustomerHealthRepository, incident_id_for
from universal_event_repository import UniversalEventRepository

_ALLOWED_EVENT_TYPES = {
    "CUSTOMER_OPERATION_FAILED",
    "CUSTOMER_SERVICE_DEGRADED",
    "CUSTOMER_INSTANCE_ACTION_FAILED",
    "CUSTOMER_PLACEMENT_FAILED",
    "CUSTOMER_ERROR_RESOLVED",
}
_ALLOWED_SEVERITIES = {"INFO", "WARNING", "ERROR", "CRITICAL"}


def _text(value: Any, limit: int = 240) -> str | None:
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    return value[:limit] or None


def _event_data(**values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        safe = _text(value, 191)
        if safe is not None:
            result[key] = safe
    return result


class CustomerHealthService:
    def __init__(self, backend):
        self.backend = backend
        self.incidents = CustomerHealthRepository(backend)
        self.events = UniversalEventRepository(backend)

    def failure(
        self,
        *,
        customer_id: str,
        controller_id: str,
        dedupe_key: str,
        event_type: str = "CUSTOMER_OPERATION_FAILED",
        severity: str = "ERROR",
        safe_code: str = "operation_failed",
        message: str = "Uma operação do cliente falhou.",
        actor_id: str | None = None,
        actor_role: str | None = None,
        action: str | None = None,
        instance_id: str | None = None,
        contract_id: str | None = None,
        correlation_id: str | None = None,
        root_type: str | None = None,
        root_id: str | None = None,
    ) -> dict[str, Any]:
        event_type = str(event_type).upper()
        severity = str(severity).upper()
        if event_type not in _ALLOWED_EVENT_TYPES - {"CUSTOMER_ERROR_RESOLVED"}:
            raise ValueError("unsupported Customer health event type")
        if severity not in _ALLOWED_SEVERITIES:
            raise ValueError("unsupported Customer health severity")
        safe_message = _text(message) or "Uma operação do cliente falhou."
        safe_code = _text(safe_code, 128) or "operation_failed"
        incident = self.incidents.open_or_recur(
            dedupe_key=dedupe_key,
            customer_id=str(customer_id),
            controller_id=str(controller_id),
            event_type=event_type,
            severity=severity,
            message=safe_message,
            instance_id=instance_id,
        )
        data = _event_data(
            customer_id=customer_id,
            incident_id=incident.get("id") or incident.get("alert_id") or incident_id_for(dedupe_key),
            safe_code=safe_code,
            action=action,
            contract_id=contract_id,
            root_type=root_type,
            root_id=root_id,
            transition=incident.get("transition"),
        )
        try:
            self.events.publish({
                "event_type": event_type,
                "source": "controller.customer_health",
                "source_id": str(controller_id),
                "severity": severity.lower(),
                "instance_id": instance_id,
                "correlation_id": correlation_id,
                "actor_type": actor_role or "customer",
                "actor_id": actor_id,
                "data": data,
            })
        except Exception:
            pass
        incident["safe_code"] = safe_code
        incident["correlation_id"] = _text(correlation_id, 191)
        incident["contract_id"] = _text(contract_id, 191)
        return incident

    def recovered(
        self,
        *,
        customer_id: str,
        controller_id: str,
        dedupe_key: str,
        correlation_id: str | None = None,
        actor_id: str | None = None,
        actor_role: str | None = None,
        instance_id: str | None = None,
    ) -> dict[str, Any] | None:
        incident = self.incidents.resolve_dedupe(dedupe_key)
        if incident is None:
            return None
        try:
            self.events.publish({
                "event_type": "CUSTOMER_ERROR_RESOLVED",
                "source": "controller.customer_health",
                "source_id": str(controller_id),
                "severity": "info",
                "instance_id": instance_id,
                "correlation_id": correlation_id,
                "actor_type": actor_role or "system",
                "actor_id": actor_id,
                "data": _event_data(customer_id=customer_id, incident_id=incident.get("id") or incident_id_for(dedupe_key)),
            })
        except Exception:
            pass
        return incident


__all__ = ["CustomerHealthService"]
