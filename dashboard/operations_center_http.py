#!/usr/bin/env python3
"""HTTP-neutral dispatcher for the administrative Operations Center."""
from __future__ import annotations

from urllib.parse import parse_qs

from operations_center_service import OperationsCenterService

OPERATIONS_PATH = "/api/operations"


def _one(query, name, default=None):
    return (query.get(name) or [default])[0]


def dispatch_operations_get(path, query_string, *, user, backend):
    if path != OPERATIONS_PATH:
        return 404, {"error": "not_found"}
    values = parse_qs(query_string or "")
    view = str(_one(values, "view", "summary") or "summary").lower()
    limit = int(_one(values, "limit", 200) or 200)
    service = OperationsCenterService(backend)
    try:
        if view == "summary":
            return 200, service.summary(user=user)
        if view == "events":
            return 200, {"events": service.list_events(
                user=user,
                limit=limit,
                event_type=_one(values, "type"),
                agent_id=_one(values, "agent_id"),
                instance_id=_one(values, "instance_id"),
                severity=_one(values, "severity"),
                correlation_id=_one(values, "correlation_id"),
            )}
        if view == "alerts":
            active = str(_one(values, "active", "0")).lower() in {"1", "true", "yes"}
            return 200, {"alerts": service.list_alerts(user=user, active_only=active, limit=limit)}
        if view == "incidents":
            active = str(_one(values, "active", "0")).lower() in {"1", "true", "yes"}
            return 200, {"incidents": service.list_incidents(user=user, limit=limit, active_only=active)}
        if view == "incident":
            return 200, {"incident": service.incident(str(_one(values, "incident_id", "") or ""), user=user)}
        if view == "schedules":
            return 200, service.schedules(user=user, limit=limit)
        if view == "logs":
            return 200, {"logs": service.logs(user=user, limit=limit)}
        return 400, {"error": "invalid_request", "message": "view inválida"}
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except KeyError:
        return 404, {"error": "not_found", "message": "Registro não encontrado."}
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "operations_query_failed", "message": "Não foi possível consultar a Central de Operações."}


def dispatch_operations_post(path, payload, *, user, backend):
    if path != OPERATIONS_PATH:
        return 404, {"error": "not_found"}
    body = dict(payload or {})
    operation = str(body.get("operation") or "").lower()
    try:
        service = OperationsCenterService(backend)
        if operation in {"acknowledge_alert", "resolve_alert"}:
            action = "acknowledge" if operation == "acknowledge_alert" else "resolve"
            alert = service.transition_alert(str(body.get("alert_id") or ""), action, user=user)
            return 200, {"alert": alert}
        if operation == "create_schedule":
            result = service.create_schedule(body.get("schedule") or {}, user=user)
            return 201, result
        if operation == "set_schedule_enabled":
            result = service.set_schedule_enabled(
                str(body.get("rule_id") or ""),
                bool(body.get("enabled")),
                user=user,
            )
            return 200, result
        return 400, {"error": "invalid_request", "message": "operation inválida"}
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except KeyError:
        return 404, {"error": "not_found", "message": "Registro não encontrado."}
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "operations_update_failed", "message": "Não foi possível atualizar a Central de Operações."}


__all__ = ["OPERATIONS_PATH", "dispatch_operations_get", "dispatch_operations_post"]
