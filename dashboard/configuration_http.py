#!/usr/bin/env python3
"""HTTP-neutral dispatch for Universal Configuration Platform."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from configuration_api import get_configuration, list_configurations, resolve_configuration, set_configuration

CONFIGURATIONS_PATH = "/api/configurations"


def dispatch_configuration_get(path: str, query_string: str, *, user, backend) -> tuple[int, dict[str, Any]]:
    if path != CONFIGURATIONS_PATH:
        return 404, {"error": "not_found"}
    query = parse_qs(query_string)
    try:
        if (query.get("resolve") or [None])[0] in {"1", "true", "yes"}:
            agent_id = str((query.get("agent_id") or [""])[0]).strip()
            if not agent_id:
                raise ValueError("agent_id is required for resolve")
            return 200, resolve_configuration(
                user=user,
                backend=backend,
                agent_id=agent_id,
                instance_id=(query.get("instance_id") or [None])[0],
            )
        namespace = (query.get("namespace") or [None])[0]
        scope_type = (query.get("scope") or [None])[0]
        scope_id = (query.get("scope_id") or [None])[0]
        if namespace and scope_type:
            return 200, get_configuration(
                user=user,
                backend=backend,
                scope_type=scope_type,
                scope_id=scope_id,
                namespace=namespace,
            )
        return 200, list_configurations(user=user, backend=backend, filters={
            "scope_type": scope_type,
            "scope_id": scope_id,
            "namespace": namespace,
            "limit": (query.get("limit") or [200])[0],
        })
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    except KeyError:
        return 404, {"error": "not_found", "message": "Configuração não encontrada."}
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "configuration_query_failed", "message": "Não foi possível consultar configurações."}


def dispatch_configuration_post(path: str, payload: dict[str, Any] | None, *, user, backend) -> tuple[int, dict[str, Any]]:
    if path != CONFIGURATIONS_PATH:
        return 404, {"error": "not_found"}
    try:
        result = set_configuration(payload, user=user, backend=backend)
        return (201 if result["changed"] and int(result["configuration"]["revision"]) == 1 else 200), result
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    except (ValueError, TypeError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "configuration_update_failed", "message": "Não foi possível atualizar a configuração."}


__all__ = ["CONFIGURATIONS_PATH", "dispatch_configuration_get", "dispatch_configuration_post"]
