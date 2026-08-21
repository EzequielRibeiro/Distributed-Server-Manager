#!/usr/bin/env python3
"""HTTP-neutral dispatch for Agent-owned instance observations."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from agent_instance_runtime_api import instance_observation_status, queue_instance_observation

INSTANCE_RUNTIME_PATH = "/api/instances/runtime-observation"


def dispatch_instance_runtime_post(path: str, payload: dict[str, Any] | None, *, user, backend) -> tuple[int, dict[str, Any]]:
    if path != INSTANCE_RUNTIME_PATH:
        return 404, {"error": "not_found"}
    try:
        return 202, queue_instance_observation(payload, user=user, backend=backend)
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    except (ValueError, KeyError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "instance_runtime_failed", "message": "Não foi possível enfileirar a observação."}


def dispatch_instance_runtime_get(path: str, query_string: str, *, user, backend) -> tuple[int, dict[str, Any]]:
    if path != INSTANCE_RUNTIME_PATH:
        return 404, {"error": "not_found"}
    query = parse_qs(query_string)
    try:
        return 200, instance_observation_status((query.get("command_id") or [""])[0], user=user, backend=backend)
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    except KeyError:
        return 404, {"error": "not_found", "message": "Comando não encontrado."}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "instance_runtime_failed", "message": "Não foi possível consultar a observação."}


__all__ = ["INSTANCE_RUNTIME_PATH", "dispatch_instance_runtime_get", "dispatch_instance_runtime_post"]
