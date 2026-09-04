#!/usr/bin/env python3
"""HTTP dispatcher for local infrastructure role administration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hybrid_demotion_api import HybridLocalDemotionError, demote_local_hybrid_for_user
from infrastructure_role_api import (
    HybridLocalReconciliationError,
    InfrastructureIdentityConflict,
    InfrastructureRoleTransitionError,
    local_role_status,
    promote_local_controller_for_user,
)

INFRASTRUCTURE_ROLE_PATH = "/api/infrastructure/role"


def dispatch_infrastructure_role_get(
    path: str,
    *,
    user: dict[str, Any] | None,
    backend,
    node_id: str | None = None,
) -> tuple[int, dict[str, Any]] | None:
    if path != INFRASTRUCTURE_ROLE_PATH:
        return None
    if not user:
        return 401, {"error": "authentication required"}
    try:
        return 200, local_role_status(backend, node_id=node_id)
    except ValueError as exc:
        return 404, {"error": str(exc)}
    except Exception:
        return 500, {"error": "failed to read infrastructure role"}


def dispatch_infrastructure_role_post(
    path: str,
    payload: dict[str, Any] | None,
    *,
    user: dict[str, Any] | None,
    backend,
    root: Path,
) -> tuple[int, dict[str, Any]] | None:
    if path != INFRASTRUCTURE_ROLE_PATH:
        return None
    data = payload if isinstance(payload, dict) else {}
    requested_role = str(data.get("role") or "").strip().lower()
    try:
        if requested_role == "controller":
            result = demote_local_hybrid_for_user(user, backend, root, data)
        else:
            result = promote_local_controller_for_user(user, backend, root, data)
        return 200, result
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except InfrastructureIdentityConflict as exc:
        return 409, {"error": str(exc)}
    except (InfrastructureRoleTransitionError, ValueError) as exc:
        return 400, {"error": str(exc)}
    except HybridLocalReconciliationError as exc:
        return 500, {
            "error": str(exc),
            "recoverable": True,
            "message": "A identidade pode já ter sido promovida. Reexecute a promoção após corrigir a reconciliação local.",
        }
    except HybridLocalDemotionError as exc:
        return 500, {
            "error": str(exc),
            "recoverable": True,
            "message": "A identidade pode já ter voltado a Controller. Reexecute a desativação após corrigir a configuração local.",
        }
    except Exception:
        return 500, {"error": "failed to change local infrastructure role"}


__all__ = [
    "INFRASTRUCTURE_ROLE_PATH",
    "dispatch_infrastructure_role_get",
    "dispatch_infrastructure_role_post",
]
