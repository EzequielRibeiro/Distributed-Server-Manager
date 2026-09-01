#!/usr/bin/env python3
"""HTTP-safe contracts for Agent update administration."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from agent_update_api import (
    agent_update_status_for_user,
    agent_update_versions_for_user,
    create_agent_rollout_for_user,
    set_agent_update_channel_for_user,
)

ROLLOUT_PATH = "/api/agents/updates/rollouts"
CHANNEL_PATH = "/api/agents/updates/channel"
STATUS_PATH = "/api/agents/updates/status"
VERSIONS_PATH = "/api/agents/updates/versions"


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


def dispatch_update_get(
    path: str,
    *,
    user,
    backend,
    agent_id: str | None,
    channel: str | None = None,
):
    try:
        if path == STATUS_PATH:
            return 200, agent_update_status_for_user(user, backend, str(agent_id or ""))
        if path == VERSIONS_PATH:
            return 200, agent_update_versions_for_user(
                user,
                backend,
                str(agent_id or ""),
                str(channel or "stable"),
            )
        return 404, {"error": "not_found"}
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Operação não permitida."}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "update_status_failed", "message": "Falha ao consultar atualização do Agent."}


def install_agent_update_http(legacy, authenticate):
    """Install the Agent update routes on the composed Dashboard handler."""
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def update_get(self):
        parsed = urlparse(self.path)
        if parsed.path not in {STATUS_PATH, VERSIONS_PATH}:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        query = parse_qs(parsed.query or "")
        status, body = dispatch_update_get(
            parsed.path,
            user=user,
            backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
            agent_id=(query.get("agent_id") or [""])[0],
            channel=(query.get("channel") or ["stable"])[0],
        )
        self.send_json(status, body)

    def update_post(self):
        parsed = urlparse(self.path)
        if parsed.path not in {ROLLOUT_PATH, CHANNEL_PATH}:
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
        status, body = dispatch_update_post(
            parsed.path,
            payload,
            user=user,
            backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
        )
        self.send_json(status, body)

    legacy.DashboardHandler.do_GET = update_get
    legacy.DashboardHandler.do_POST = update_post


__all__ = [
    "ROLLOUT_PATH",
    "CHANNEL_PATH",
    "STATUS_PATH",
    "VERSIONS_PATH",
    "dispatch_update_post",
    "dispatch_update_get",
    "install_agent_update_http",
]
