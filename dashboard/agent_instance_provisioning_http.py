#!/usr/bin/env python3
"""HTTP-neutral dispatch for Agent-owned instance provisioning."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from agent_instance_provisioning_api import instance_provisioning_status, queue_instance_provisioning

INSTANCE_PROVISIONING_PATH = "/api/instances/provisioning"


def dispatch_instance_provisioning_post(
    path: str,
    payload: dict[str, Any] | None,
    *,
    user,
    backend,
    root: Path,
) -> tuple[int, dict[str, Any]]:
    if path != INSTANCE_PROVISIONING_PATH:
        return 404, {"error": "not_found"}
    try:
        return 202, queue_instance_provisioning(payload, user=user, backend=backend, root=root)
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    except (ValueError, KeyError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "instance_provisioning_failed", "message": "Não foi possível enfileirar o provisioning."}


def dispatch_instance_provisioning_get(path: str, query_string: str, *, user, backend) -> tuple[int, dict[str, Any]]:
    if path != INSTANCE_PROVISIONING_PATH:
        return 404, {"error": "not_found"}
    query = parse_qs(query_string)
    try:
        return 200, instance_provisioning_status((query.get("job_id") or [""])[0], user=user, backend=backend)
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    except KeyError:
        return 404, {"error": "not_found", "message": "Provisioning job não encontrado."}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "instance_provisioning_failed", "message": "Não foi possível consultar o provisioning."}


__all__ = ["INSTANCE_PROVISIONING_PATH", "dispatch_instance_provisioning_get", "dispatch_instance_provisioning_post"]
