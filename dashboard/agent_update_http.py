#!/usr/bin/env python3
"""HTTP-safe contracts for Agent update administration."""

from __future__ import annotations

from typing import Any

from agent_update_api import (
    agent_update_status_for_user,
    create_agent_rollout_for_user,
    set_agent_update_channel_for_user,
)

ROLLOUT_PATH = "/api/agents/updates/rollouts"
CHANNEL_PATH = "/api/agents/updates/channel"
STATUS_PATH = "/api/agents/updates/status"


def dispatch_update_post(path: str, payload: dict[str, Any] | None, *, user, backend):
    try:
        if path == ROLLOUT_PATH:
            return 201, create_agent_rollout_for_user(user, backend, payload)
        if path == CHANNEL_PATH:
            return 200, set_agent_update_channel_for_user(user, backend, payload)
        return 404, {"error": "not_found"}
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Operação não permitida."}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "update_admin_failed", "message": "Falha ao administrar atualização do Agent."}


def dispatch_update_get(path: str, *, user, backend, agent_id: str | None):
    try:
        if path != STATUS_PATH:
            return 404, {"error": "not_found"}
        return 200, agent_update_status_for_user(user, backend, str(agent_id or ""))
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Operação não permitida."}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "update_status_failed", "message": "Falha ao consultar atualização do Agent."}


__all__ = ["ROLLOUT_PATH", "CHANNEL_PATH", "STATUS_PATH", "dispatch_update_post", "dispatch_update_get"]
