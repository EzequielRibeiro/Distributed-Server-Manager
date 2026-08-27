#!/usr/bin/env python3
"""Customer functional health projection on top of the existing alert store."""
from __future__ import annotations

import hashlib
from typing import Any

from alert_repository import AlertRepository

CUSTOMER_SCOPE_PREFIX = "customer:"


def incident_id_for(dedupe_key: str) -> str:
    digest = hashlib.sha256(str(dedupe_key).encode("utf-8")).hexdigest()[:40]
    return f"customer-health-{digest}"


def customer_id_from_scope(scope: str | None) -> str | None:
    value = str(scope or "")
    return value[len(CUSTOMER_SCOPE_PREFIX):] if value.startswith(CUSTOMER_SCOPE_PREFIX) else None


class CustomerHealthRepository:
    """Reuse the canonical `alerts` + `alert_events` tables without changing Baseline v2."""

    def __init__(self, backend):
        self.backend = backend
        self.alerts = AlertRepository(backend)

    def open_or_recur(
        self,
        *,
        dedupe_key: str,
        customer_id: str,
        controller_id: str,
        event_type: str,
        severity: str,
        message: str,
        instance_id: str | None = None,
    ) -> dict[str, Any]:
        alert_id = incident_id_for(dedupe_key)
        before = self.alerts.get_alert(alert_id)
        result = self.alerts.open_alert(
            alert_id=alert_id,
            rule_id=str(event_type).upper(),
            level=str(severity).upper(),
            message=str(message),
            scope=CUSTOMER_SCOPE_PREFIX + str(customer_id),
            controller_id=str(controller_id),
            instance_id=str(instance_id) if instance_id else None,
        )
        result["customer_id"] = str(customer_id)
        result["transition"] = result.pop("action", "UNCHANGED")
        result["recurrence"] = bool(before and before.get("state") in {"RESOLVED", "SUPPRESSED"})
        return result

    def get(self, incident_id: str) -> dict[str, Any] | None:
        item = self.alerts.get_alert(str(incident_id))
        if item is None:
            return None
        customer_id = customer_id_from_scope(item.get("scope"))
        if customer_id is None:
            return None
        item["customer_id"] = customer_id
        return item

    def history(self, incident_id: str) -> list[dict[str, Any]]:
        if self.get(incident_id) is None:
            return []
        return self.alerts.alert_history(str(incident_id))

    def acknowledge(self, incident_id: str) -> dict[str, Any] | None:
        current = self.get(incident_id)
        if current is None:
            return None
        result = self.alerts.acknowledge_alert(str(incident_id))
        result["customer_id"] = current["customer_id"]
        return result

    def resolve(self, incident_id: str) -> dict[str, Any] | None:
        current = self.get(incident_id)
        if current is None:
            return None
        result = self.alerts.resolve_alert(str(incident_id))
        if result is not None:
            result["customer_id"] = current["customer_id"]
        return result

    def resolve_dedupe(self, dedupe_key: str) -> dict[str, Any] | None:
        return self.resolve(incident_id_for(dedupe_key))

    def list_incidents(
        self,
        *,
        customer_id: str | None = None,
        controller_id: str | None = None,
        active_only: bool = True,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {}
        if controller_id is not None:
            filters["controller_id"] = str(controller_id)
        rows = self.alerts.list_alerts(active_only=active_only, limit=max(1, min(int(limit), 1000)), **filters)
        result: list[dict[str, Any]] = []
        for row in rows:
            scoped_customer = customer_id_from_scope(row.get("scope"))
            if scoped_customer is None:
                continue
            if customer_id is not None and scoped_customer != str(customer_id):
                continue
            item = dict(row)
            item["customer_id"] = scoped_customer
            result.append(item)
        return result


__all__ = ["CUSTOMER_SCOPE_PREFIX", "CustomerHealthRepository", "customer_id_from_scope", "incident_id_for"]
