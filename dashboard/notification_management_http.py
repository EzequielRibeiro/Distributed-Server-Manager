#!/usr/bin/env python3
"""Administrative HTTP surface for database-backed notification delivery."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from activity_audit_repository import ActivityAuditRepository
from activity_humanizer import actor_name
from controller_session import session_user_from_headers
from notification_routing_repository import NotificationRoutingRepository

DESTINATIONS_API = "/api/admin/notification/destinations"
DESTINATION_API = "/api/admin/notification/destination"
DESTINATION_STATE_API = "/api/admin/notification/destination/state"
ROUTES_API = "/api/admin/notification/routes"
ROUTE_API = "/api/admin/notification/route"
ROUTE_STATE_API = "/api/admin/notification/route/state"


def install_notification_management(legacy, authenticate) -> None:
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST
    previous_put = getattr(legacy.DashboardHandler, "do_PUT", None)

    def backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def identity(headers):
        return session_user_from_headers(headers) or authenticate(headers)

    def authorized(self):
        user = identity(self.headers)
        if user is None:
            self.unauthorized()
            return None
        if str(user.get("role") or "").lower() not in {"admin", "controller"}:
            self.send_json(403, {"error": "forbidden"})
            return None
        return user

    def audit(user, *, action, target_type, target_id, target_name, summary, changes=None):
        ActivityAuditRepository(backend()).record_action(
            actor_id=str(user.get("username") or user.get("id") or "").strip() or None,
            actor_name=actor_name(user),
            actor_role=str(user.get("role") or "").strip() or None,
            action=action,
            category="notifications",
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            result="success",
            summary=summary,
            changes=changes or {},
        )

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path not in {DESTINATIONS_API, ROUTES_API}:
            return previous_get(self)
        if authorized(self) is None:
            return
        repo = NotificationRoutingRepository(backend())
        query = parse_qs(parsed.query)
        if parsed.path == DESTINATIONS_API:
            enabled_only = str((query.get("enabled") or ["false"])[0]).lower() in {"1", "true", "yes"}
            rows = repo.list_destinations(enabled_only=enabled_only)
            self.send_json(200, {"destinations": rows, "count": len(rows)})
            return
        destination_id = str((query.get("destination_id") or [""])[0]).strip() or None
        rows = repo.list_routes(destination_id=destination_id)
        self.send_json(200, {"routes": rows, "count": len(rows)})

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path not in {DESTINATION_API, DESTINATION_STATE_API, ROUTE_API, ROUTE_STATE_API}:
            return previous_post(self)
        user = authorized(self)
        if user is None:
            return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid request"})
            return
        repo = NotificationRoutingRepository(backend())
        who = actor_name(user)
        try:
            if parsed.path == DESTINATION_API:
                destination_id = repo.create_destination(
                    name=payload.get("name"),
                    channel=payload.get("channel"),
                    recipient=payload.get("recipient"),
                    secret_file=payload.get("secret_file"),
                    config=payload.get("config"),
                    enabled=bool(payload.get("enabled", True)),
                )
                destination = repo.get_destination(destination_id)
                audit(
                    user,
                    action="notification.destination.created",
                    target_type="notification_destination",
                    target_id=destination_id,
                    target_name=str((destination or {}).get("name") or destination_id),
                    summary=f"{who} criou o destino de notificação {(destination or {}).get('name') or destination_id}.",
                    changes={"created": {"before": None, "after": destination}},
                )
                self.send_json(201, {"destination": destination})
                return
            if parsed.path == DESTINATION_STATE_API:
                destination_id = str(payload.get("destination_id") or "").strip()
                before = repo.get_destination(destination_id)
                if before is None:
                    self.send_json(404, {"error": "notification destination not found"})
                    return
                enabled = bool(payload.get("enabled"))
                repo.set_destination_enabled(destination_id, enabled)
                after = repo.get_destination(destination_id)
                audit(
                    user,
                    action="notification.destination.state_changed",
                    target_type="notification_destination",
                    target_id=destination_id,
                    target_name=str(before.get("name") or destination_id),
                    summary=f"{who} {'ativou' if enabled else 'desativou'} o destino de notificação {before.get('name') or destination_id}.",
                    changes={"enabled": {"before": before.get("enabled"), "after": enabled}},
                )
                self.send_json(200, {"destination": after})
                return
            if parsed.path == ROUTE_API:
                route_id = repo.create_route(
                    destination_id=payload.get("destination_id"),
                    event_type=payload.get("event_type"),
                    minimum_severity=payload.get("minimum_severity") or "warning",
                    enabled=bool(payload.get("enabled", True)),
                )
                route = next((item for item in repo.list_routes() if item.get("route_id") == route_id), None)
                audit(
                    user,
                    action="notification.route.created",
                    target_type="notification_route",
                    target_id=route_id,
                    target_name=str((route or {}).get("event_type") or "todos os eventos"),
                    summary=f"{who} criou uma regra de roteamento de notificações.",
                    changes={"created": {"before": None, "after": route}},
                )
                self.send_json(201, {"route": route})
                return
            route_id = str(payload.get("route_id") or "").strip()
            route = next((item for item in repo.list_routes() if item.get("route_id") == route_id), None)
            if route is None:
                self.send_json(404, {"error": "notification route not found"})
                return
            enabled = bool(payload.get("enabled"))
            repo.set_route_enabled(route_id, enabled)
            audit(
                user,
                action="notification.route.state_changed",
                target_type="notification_route",
                target_id=route_id,
                target_name=str(route.get("event_type") or "todos os eventos"),
                summary=f"{who} {'ativou' if enabled else 'desativou'} uma regra de roteamento de notificações.",
                changes={"enabled": {"before": route.get("enabled"), "after": enabled}},
            )
            self.send_json(200, {"route": next((item for item in repo.list_routes() if item.get("route_id") == route_id), None)})
        except (ValueError, TypeError) as exc:
            self.send_json(400, {"error": str(exc)})

    def do_put(self):
        parsed = urlparse(self.path)
        if parsed.path != DESTINATION_API:
            if previous_put is not None:
                return previous_put(self)
            self.send_json(404, {"error": "not_found"})
            return
        user = authorized(self)
        if user is None:
            return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid request"})
            return
        repo = NotificationRoutingRepository(backend())
        destination_id = str(payload.get("destination_id") or "").strip()
        before = repo.get_destination(destination_id)
        if before is None:
            self.send_json(404, {"error": "notification destination not found"})
            return
        try:
            after = repo.update_destination(
                destination_id,
                name=payload.get("name"),
                recipient=payload.get("recipient"),
                secret_file=payload.get("secret_file"),
                config=payload.get("config"),
                enabled=bool(payload.get("enabled", True)),
            )
        except (ValueError, TypeError) as exc:
            self.send_json(400, {"error": str(exc)})
            return
        who = actor_name(user)
        audit(
            user,
            action="notification.destination.updated",
            target_type="notification_destination",
            target_id=destination_id,
            target_name=str((after or {}).get("name") or destination_id),
            summary=f"{who} alterou o destino de notificação {(after or {}).get('name') or destination_id}.",
            changes={
                key: {"before": before.get(key), "after": (after or {}).get(key)}
                for key in ("name", "recipient", "secret_file", "config", "enabled")
                if before.get(key) != (after or {}).get(key)
            },
        )
        self.send_json(200, {"destination": after})

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post
    legacy.DashboardHandler.do_PUT = do_put


__all__ = [
    "DESTINATIONS_API", "DESTINATION_API", "DESTINATION_STATE_API",
    "ROUTES_API", "ROUTE_API", "ROUTE_STATE_API", "install_notification_management",
]
