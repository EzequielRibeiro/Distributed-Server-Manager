#!/usr/bin/env python3
"""Administrative Operations Center: events, alerts, incidents, schedules and history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from alert_repository import AlertRepository
from automation_repository import AutomationRepository
from universal_event_repository import UniversalEventRepository

ADMIN_ROLES = {"admin", "controller", "operator"}
TERMINAL_MARKERS = ("COMPLETED", "SUCCEEDED", "RESOLVED", "RECOVERED", "FINISHED", "CLOSED")
FAILURE_MARKERS = ("FAILED", "ERROR", "CRITICAL", "UNAVAILABLE", "REJECTED")


def _require_admin(user: dict[str, Any] | None) -> None:
    if not user or str(user.get("role") or "").lower() not in ADMIN_ROLES:
        raise PermissionError("Acesso administrativo necessário.")


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _event_time(event: dict[str, Any]) -> str:
    return _iso(event.get("occurred_at") or event.get("received_at"))


def _incident_key(event: dict[str, Any]) -> str:
    correlation = str(event.get("correlation_id") or "").strip()
    if correlation:
        return correlation
    return str(event.get("event_id") or "")


def _terminal(event_type: str) -> bool:
    upper = str(event_type or "").upper()
    return any(marker in upper for marker in TERMINAL_MARKERS)


def _failure(event_type: str) -> bool:
    upper = str(event_type or "").upper()
    return any(marker in upper for marker in FAILURE_MARKERS)


def _severity_rank(value: str) -> int:
    return {"critical": 4, "error": 3, "warning": 2, "warn": 2, "info": 1}.get(str(value or "").lower(), 0)


class OperationsCenterService:
    def __init__(self, backend):
        self.backend = backend
        self.events = UniversalEventRepository(backend)
        self.alerts = AlertRepository(backend)
        self.automation = AutomationRepository(backend)

    def initialize(self) -> None:
        self.events.initialize()
        self.alerts.initialize()
        self.automation.initialize()

    def list_events(self, *, user, limit=200, **filters):
        _require_admin(user)
        self.initialize()
        return self.events.list_events(limit=max(1, min(int(limit), 1000)), **filters)

    def list_alerts(self, *, user, active_only=False, limit=200):
        _require_admin(user)
        self.initialize()
        return self.alerts.list_alerts(active_only=bool(active_only), limit=max(1, min(int(limit), 1000)))

    def _incident_groups(self, source_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for event in source_events:
            groups.setdefault(_incident_key(event), []).append(event)
        incidents: list[dict[str, Any]] = []
        for incident_id, events in groups.items():
            events.sort(key=_event_time)
            if not any(_severity_rank(e.get("severity")) >= 2 or _failure(e.get("event_type")) for e in events):
                continue
            peak = max(events, key=lambda e: _severity_rank(e.get("severity")))
            terminal = next((e for e in reversed(events) if _terminal(e.get("event_type"))), None)
            failed = next((e for e in reversed(events) if _failure(e.get("event_type"))), None)
            status = "resolved" if terminal and (not failed or _event_time(terminal) >= _event_time(failed)) else "open"
            first, last = events[0], events[-1]
            incidents.append({
                "incident_id": incident_id,
                "correlation_id": first.get("correlation_id"),
                "status": status,
                "severity": str(peak.get("severity") or "warning").lower(),
                "title": str(peak.get("event_type") or "INCIDENT"),
                "source": peak.get("source"),
                "source_id": peak.get("source_id"),
                "agent_id": next((e.get("agent_id") for e in events if e.get("agent_id")), None),
                "instance_id": next((e.get("instance_id") for e in events if e.get("instance_id")), None),
                "started_at": _event_time(first),
                "updated_at": _event_time(last),
                "resolved_at": _event_time(terminal) if status == "resolved" and terminal else None,
                "event_count": len(events),
                "events": events,
            })
        incidents.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return incidents

    def list_incidents(self, *, user, limit=300, active_only=False):
        events = self.list_events(user=user, limit=limit)
        items = self._incident_groups(events)
        if active_only:
            items = [item for item in items if item["status"] == "open"]
        return items

    def incident(self, incident_id: str, *, user):
        _require_admin(user)
        if not str(incident_id or "").strip():
            raise ValueError("incident_id obrigatório")
        incidents = self.list_incidents(user=user, limit=1000)
        item = next((value for value in incidents if value["incident_id"] == incident_id), None)
        if item is None:
            raise KeyError(incident_id)
        related_alerts = []
        for alert in self.list_alerts(user=user, active_only=False, limit=500):
            same_agent = item.get("agent_id") and alert.get("agent_id") == item.get("agent_id")
            same_instance = item.get("instance_id") and alert.get("instance_id") == item.get("instance_id")
            if same_agent or same_instance:
                related_alerts.append(alert)
        item = dict(item)
        item["alerts"] = related_alerts
        return item

    def schedules(self, *, user, limit=200):
        _require_admin(user)
        self.initialize()
        rules = self.automation.list_rules(limit=limit)
        runs = self.automation.list_runs(limit=limit)
        failed = [run for run in runs if str(run.get("status") or "").lower() in {"failed", "error"}]
        return {"rules": rules, "runs": runs, "failed_runs": len(failed)}

    def logs(self, *, user, limit=300):
        events = self.list_events(user=user, limit=limit)
        return [{
            "timestamp": _event_time(event),
            "level": str(event.get("severity") or "info").lower(),
            "source": event.get("source"),
            "source_id": event.get("source_id"),
            "event_type": event.get("event_type"),
            "correlation_id": event.get("correlation_id"),
            "agent_id": event.get("agent_id"),
            "instance_id": event.get("instance_id"),
            "message": (event.get("data") or {}).get("message") or (event.get("data") or {}).get("error") or event.get("event_type"),
            "data": event.get("data") or {},
        } for event in events]

    def summary(self, *, user):
        _require_admin(user)
        self.initialize()
        active_alerts = self.alerts.list_alerts(active_only=True, limit=500)
        incidents = self.list_incidents(user=user, limit=500, active_only=True)
        events = self.events.list_events(limit=50)
        runs = self.automation.list_runs(limit=50)
        return {
            "active_alerts": len(active_alerts),
            "critical_alerts": sum(1 for a in active_alerts if str(a.get("level") or "").upper() == "CRITICAL"),
            "active_incidents": len(incidents),
            "critical_incidents": sum(1 for i in incidents if i.get("severity") == "critical"),
            "recent_events": len(events),
            "failed_schedule_runs": sum(1 for r in runs if str(r.get("status") or "").lower() in {"failed", "error"}),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "incidents": incidents[:5],
        }

    def transition_alert(self, alert_id: str, action: str, *, user):
        _require_admin(user)
        self.initialize()
        action = str(action or "").lower()
        if action == "acknowledge":
            return self.alerts.acknowledge_alert(alert_id)
        if action == "resolve":
            result = self.alerts.resolve_alert(alert_id)
            if result is None:
                raise KeyError(alert_id)
            return result
        raise ValueError("action deve ser acknowledge ou resolve")


__all__ = ["OperationsCenterService", "ADMIN_ROLES"]
