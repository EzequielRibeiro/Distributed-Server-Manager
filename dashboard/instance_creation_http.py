#!/usr/bin/env python3
"""HTTP boundary for customer instance creation.

Placement/domain failures are converted into stable HTTP responses here so no
exception from instance placement can reach ``socketserver``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from placement_errors import PlacementUnavailable


INSTANCE_CREATE_PATH = "/api/instance/create"
PLACEMENT_UNAVAILABLE_MESSAGE = (
    "Nenhum ambiente está disponível para criar este servidor."
)
_LOGGER = logging.getLogger("capivara.instance_creation")


def _requested_region(payload: dict[str, Any]) -> str | None:
    placement = payload.get("placement")
    source = placement if isinstance(placement, dict) else payload
    value = source.get("region_id") or source.get("region")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _contract_id(
    user: dict[str, Any] | None,
    payload: dict[str, Any],
    contract_resolver: Callable[[dict[str, Any] | None, str], str | None] | None,
) -> str | None:
    if contract_resolver is None:
        return None
    game = str(payload.get("game", "")).strip().lower()
    try:
        return contract_resolver(user, game)
    except Exception:
        return None


def _log_rejection(
    *,
    user: dict[str, Any] | None,
    payload: dict[str, Any],
    exc: PlacementUnavailable,
    contract_resolver: Callable[[dict[str, Any] | None, str], str | None] | None,
    log: Callable[[str], None] | None,
) -> None:
    record = {
        "event": "instance_create_rejected",
        "customer": None if not user else user.get("scope_id"),
        "contract": _contract_id(user, payload, contract_resolver),
        "game": str(payload.get("game", "")).strip().lower() or None,
        "region": exc.requested_region_id or _requested_region(payload),
        "reason": exc.reason,
        "agents_evaluated": int(exc.agents_evaluated),
    }
    message = json.dumps(record, ensure_ascii=False, sort_keys=True)
    if log is not None:
        log(message)
    else:
        _LOGGER.warning(message)


def dispatch_instance_create_post(
    path: str,
    payload: dict[str, Any] | None,
    *,
    user: dict[str, Any] | None,
    create_instance: Callable[[dict[str, Any] | None, dict[str, Any]], dict[str, Any]],
    contract_resolver: Callable[[dict[str, Any] | None, str], str | None] | None = None,
    log: Callable[[str], None] | None = None,
    failure_reporter: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[int, dict[str, Any]] | None:
    """Handle ``POST /api/instance/create`` without leaking domain failures."""

    if path != INSTANCE_CREATE_PATH:
        return None

    if not isinstance(payload, dict):
        return 400, {"error": "invalid_request", "message": "Requisição inválida."}

    try:
        result = create_instance(user, payload)
        return 201, result

    except PlacementUnavailable as exc:
        _log_rejection(
            user=user,
            payload=payload,
            exc=exc,
            contract_resolver=contract_resolver,
            log=log,
        )
        _report_failure(failure_reporter, user, payload, "placement_unavailable", str(exc))
        return 409, {
            "error": "placement_unavailable",
            "message": PLACEMENT_UNAVAILABLE_MESSAGE,
        }

    except PermissionError as exc:
        _report_failure(failure_reporter, user, payload, "forbidden", str(exc))
        return 403, {
            "error": "forbidden",
            "message": "Operação não permitida.",
        }

    except ValueError as exc:
        _report_failure(failure_reporter, user, payload, "invalid_request", str(exc))
        return 400, {
            "error": "invalid_request",
            "message": str(exc),
        }

    except Exception as exc:
        _LOGGER.exception("instance creation failed at HTTP boundary")
        _report_failure(failure_reporter, user, payload, "instance_creation_failed", str(exc))
        return 500, {
            "error": "instance_creation_failed",
            "message": "Não foi possível criar o servidor.",
        }


def _report_failure(reporter, user, payload, code: str, reason: str) -> None:
    if reporter is None:
        return
    try:
        reporter({
            "code": code,
            "reason": reason,
            "username": None if not user else user.get("username"),
            "customer_id": None if not user else user.get("scope_id"),
            "contract_id": str(payload.get("contract_id") or "").strip() or None,
            "game": str(payload.get("game") or "").strip().lower() or None,
            "placement": payload.get("placement") if isinstance(payload.get("placement"), dict) else {},
        })
    except Exception:
        _LOGGER.exception("could not persist instance creation failure")


__all__ = [
    "INSTANCE_CREATE_PATH",
    "PLACEMENT_UNAVAILABLE_MESSAGE",
    "dispatch_instance_create_post",
]
