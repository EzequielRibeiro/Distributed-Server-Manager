#!/usr/bin/env python3
"""Dashboard service for safe local Hybrid -> Controller demotion."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from hybrid_local_demotion import HybridLocalDemotionError, reconcile_local_controller_config
from infrastructure_role_api import local_role_status
from infrastructure_role_transition import InfrastructureRoleTransitionError, demote_hybrid_to_controller
from registry_repository import RegistryRepository


def demote_local_hybrid_for_user(
    user: dict[str, Any] | None,
    backend,
    root: Path,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if not user or str(user.get("role") or "").strip().lower() != "admin":
        raise PermissionError("admin role required")

    data = payload if isinstance(payload, dict) else {}
    if str(data.get("role") or "").strip().lower() != "controller":
        raise ValueError("role must be controller")

    node_id = str(data.get("node_id") or socket.gethostname()).strip()
    before = local_role_status(backend, node_id=node_id)
    if before.get("role") not in {"hybrid", "controller"}:
        raise InfrastructureRoleTransitionError(
            f"Node {node_id} has role {before.get('role')}; only hybrid -> controller is supported"
        )
    controller_id = str(before.get("controller_id") or "").strip()
    if not controller_id:
        raise InfrastructureRoleTransitionError(f"Node {node_id} has no Controller identity")

    transition = demote_hybrid_to_controller(
        RegistryRepository(backend),
        node_id=node_id,
        controller_id=controller_id,
        agent_id=before.get("agent_id"),
    )

    try:
        reconciliation = reconcile_local_controller_config(Path(root), node_id=node_id)
    except HybridLocalDemotionError:
        raise
    except Exception as exc:
        raise HybridLocalDemotionError(
            "persisted Hybrid demotion succeeded, but local configuration cleanup failed"
        ) from exc

    after = local_role_status(backend, node_id=node_id)
    return {**after, "transition": transition, "reconciliation": reconciliation}


__all__ = ["HybridLocalDemotionError", "demote_local_hybrid_for_user"]
