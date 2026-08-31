#!/usr/bin/env python3
"""Database-backed administrative alert HTTP surface."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from activity_audit_repository import ActivityAuditRepository
from activity_humanizer import actor_name
from alert_repository import AlertRepository
from controller_session import session_user_from_headers

ALERTS_API = "/api/admin/alerts"
ALERT_API = "/api/admin/alert"
ALERT_ACTION_API = "/api/admin/alert/action"
IDENTITY_COLLISION_RULE_ID = "agent.identity_collision"


def generic_alert_action_allowed(alert, action: str) -> bool:
    """Keep specialized incidents out of generic resolution paths."""
    normalized_action = str(action or "").strip().lower()
    rule_id = str((alert or {}).get("rule_id") or "").strip()
    return not (
        normalized_action == "resolve"
        and rule_id == IDENTITY_COLLISION_RULE_ID
    )


def install_alert_management(legacy, authenticate) -> None:
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def identity(headers):
        return session_user_from_headers(headers) or authenticate(headers)

    def authorized(self):
        user = identity(self.headers)
        if user is None:
            self.unauthorized()
            return None
        if str(user.get("role") or "").lower() not in {"admin", "controller", "operator"}:
            self.send_json(403, {"error": "forbidden"})
            return None
        return user

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path not in {ALERTS_API, ALERT_API}:
            return previous_get(self)
        if authorized(self) is None:
            return
        current_backend = backend()
        repo = AlertRepository(current_backend)
        query = parse_qs(parsed.query)
        if parsed.path == ALERT_API:
            alert_id = str((query.get("id") or [""])[0]).strip()
            if not alert_id:
                self.send_json(400, {"error": "alert id is required"})
                return
            alert = repo.get_alert(alert_id)
            if alert is None:
                self.send_json(404, {"error": "alert not found"})
                return
            audit = ActivityAuditRepository(current_backend).search(
                category="alerts",
                target_type="alert",
                target_id=alert_id,
                limit=200,
            )
            self.send_json(
                200,
                {
                    "alert": alert,
                    "history": repo.alert_history(alert_id),
                    "audit": audit,
                },
            )
            return
        active = str((query.get("active") or ["true"])[0]).lower() not in {"0", "false", "no"}
        level = str((query.get("level") or [""])[0]).strip().upper() or None
        state = str((query.get("state") or [""])[0]).strip().upper() or None
        agent_id = str((query.get("agent_id") or [""])[0]).strip() or None
        instance_id = str((query.get("instance_id") or [""])[0]).strip() or None
        try:
            limit = int((query.get("limit") or ["200"])[0])
        except ValueError:
            limit = 200
        filters = {}
        if level:
            filters["level"] = level
        if state:
            filters["state"] = state
        if agent_id:
            filters["agent_id"] = agent_id
        if instance_id:
            filters["instance_id"] = instance_id
        alerts = repo.list_alerts(active_only=active, limit=max(1, min(limit, 1000)), **filters)
        self.send_json(200, {"alerts": alerts, "count": len(alerts)})

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path != ALERT_ACTION_API:
            return previous_post(self)
        user = authorized(self)
        if user is None:
            return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid request"})
            return
        alert_id = str(payload.get("id") or payload.get("alert_id") or "").strip()
        action = str(payload.get("action") or "").strip().lower()
        allowed = {"acknowledge", "resolve", "suppress", "note", "reopen"}
        if not alert_id or action not in allowed:
            self.send_json(400, {"error": "invalid alert action"})
            return
        note = str(payload.get("note") or payload.get("message") or "").strip()
        current_backend = backend()
        repo = AlertRepository(current_backend)
        before = repo.get_alert(alert_id)
        if before is None:
            self.send_json(404, {"error": "alert not found"})
            return
        if not generic_alert_action_allowed(before, action):
            self.send_json(
                409,
                {
                    "error": (
                        "identity collision alerts must be resolved through the "
                        "Agent identity repair workflow"
                    ),
                    "code": "specialized_resolution_required",
                    "rule_id": IDENTITY_COLLISION_RULE_ID,
                },
            )
            return
        try:
            if action == "acknowledge":
                result = repo.acknowledge_alert(alert_id)
                human_action = "alert.acknowledged"
                verb = "reconheceu"
            elif action == "resolve":
                result = repo.resolve_alert(alert_id, note=note or None)
                human_action = "alert.resolved"
                verb = "resolveu"
            elif action == "note":
                if not note:
                    raise ValueError("alert note is required")
                result = repo.note_alert(alert_id, note)
                human_action = "alert.note_added"
                verb = "adicionou uma nota em"
            elif action == "reopen":
                result = repo.reopen_alert(alert_id, note=note or None)
                human_action = "alert.reopened"
                verb = "reabriu"
            else:
                minutes = int(payload.get("minutes") or 60)
                result = repo.suppress_alert(alert_id, minutes)
                human_action = "alert.suppressed"
                verb = "suprimiu"
        except (ValueError, TypeError) as exc:
            self.send_json(400, {"error": str(exc)})
            return
        who = actor_name(user)
        actor_id = str(user.get("username") or user.get("id") or "").strip() or None
        actor_role = str(user.get("role") or "").strip() or None
        changes = {
            "state": {
                "before": before.get("state"),
                "after": (result or {}).get("state"),
            }
        }
        if note:
            changes["note"] = {"after": note[:4000]}
        ActivityAuditRepository(current_backend).record_action(
            actor_id=actor_id,
            actor_name=who,
            actor_role=actor_role,
            action=human_action,
            category="alerts",
            target_type="alert",
            target_id=alert_id,
            target_name=str(before.get("message") or alert_id),
            result="success",
            summary=f"{who} {verb} o alerta: {before.get('message') or alert_id}.",
            changes=changes,
        )
        self.send_json(
            200,
            {
                "alert": result,
                "actor": {
                    "id": actor_id,
                    "name": who,
                    "role": actor_role,
                },
            },
        )

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = [
    "ALERTS_API",
    "ALERT_API",
    "ALERT_ACTION_API",
    "IDENTITY_COLLISION_RULE_ID",
    "generic_alert_action_allowed",
    "install_alert_management",
]
