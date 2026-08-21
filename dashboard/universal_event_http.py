#!/usr/bin/env python3
"""HTTP-neutral dispatch for the Universal Event Platform."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from universal_event_api import get_event, list_events, publish_event

EVENTS_PATH = "/api/events"


def dispatch_universal_event_get(path: str, query_string: str, *, user, backend) -> tuple[int, dict[str, Any]]:
    if path != EVENTS_PATH:
        return 404, {"error": "not_found"}
    query = parse_qs(query_string)
    event_id = (query.get("event_id") or [None])[0]
    try:
        if event_id:
            return 200, get_event(event_id, user=user, backend=backend)
        return 200, list_events(user=user, backend=backend, filters={
            "event_type": (query.get("type") or [None])[0],
            "agent_id": (query.get("agent_id") or [None])[0],
            "instance_id": (query.get("instance_id") or [None])[0],
            "severity": (query.get("severity") or [None])[0],
            "correlation_id": (query.get("correlation_id") or [None])[0],
            "limit": (query.get("limit") or [100])[0],
        })
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    except KeyError:
        return 404, {"error": "not_found", "message": "Evento não encontrado."}
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "event_query_failed", "message": "Não foi possível consultar eventos."}


def dispatch_universal_event_post(path: str, payload: dict[str, Any] | None, *, user, backend) -> tuple[int, dict[str, Any]]:
    if path != EVENTS_PATH:
        return 404, {"error": "not_found"}
    try:
        result = publish_event(payload, user=user, backend=backend)
        return (201 if result["created"] else 200), result
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "event_publish_failed", "message": "Não foi possível publicar o evento."}


__all__ = ["EVENTS_PATH", "dispatch_universal_event_get", "dispatch_universal_event_post"]
