#!/usr/bin/env python3
"""Transport-neutral HTTP dispatcher for Agent-owned game-data operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from agent_game_data_api import game_data_job_status, queue_game_data_operation

GAME_DATA_JOBS_PATH = "/api/agents/game-data/jobs"
GAME_DATA_OPERATION_PATH = "/api/agents/game-data"
LEGACY_ENVIRONMENT_INSTALL_PATH = "/api/catalog/environment-install"


def dispatch_agent_game_data_get(
    path: str,
    query_string: str,
    *,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    if path != GAME_DATA_JOBS_PATH:
        return None
    query = parse_qs(query_string, keep_blank_values=True)
    try:
        body = game_data_job_status(
            user,
            backend=backend,
            job_id=(query.get("job_id") or [None])[0],
            agent_id=(query.get("agent_id") or [None])[0],
        )
        return 200, body
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except KeyError:
        return 404, {"error": "game_data_job_not_found", "message": "Operação de game-data não encontrada."}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "game_data_status_failed", "message": "Não foi possível consultar game-data."}


def dispatch_agent_game_data_post(
    path: str,
    payload: dict[str, Any] | None,
    *,
    user: dict[str, Any] | None,
    backend,
    root: Path,
) -> tuple[int, dict[str, Any]] | None:
    if path not in {GAME_DATA_OPERATION_PATH, LEGACY_ENVIRONMENT_INSTALL_PATH}:
        return None
    body = dict(payload or {})
    if path == LEGACY_ENVIRONMENT_INSTALL_PATH:
        body.setdefault("action", "install")
    try:
        result = queue_game_data_operation(user, body, backend=backend, root=root)
        return 202, result
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except RuntimeError as exc:
        return 409, {"error": "game_data_prepare_failed", "message": str(exc)}
    except Exception:
        return 500, {"error": "game_data_queue_failed", "message": "Não foi possível enfileirar game-data."}


__all__ = [
    "GAME_DATA_JOBS_PATH",
    "GAME_DATA_OPERATION_PATH",
    "LEGACY_ENVIRONMENT_INSTALL_PATH",
    "dispatch_agent_game_data_get",
    "dispatch_agent_game_data_post",
]
