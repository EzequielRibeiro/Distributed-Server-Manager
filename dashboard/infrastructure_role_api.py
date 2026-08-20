#!/usr/bin/env python3
"""Dashboard API boundary for safe local infrastructure role administration."""

from __future__ import annotations

import re
import socket
from pathlib import Path
from typing import Any

from hybrid_local_reconciliation import (
    HybridLocalReconciliationError,
    reconcile_local_hybrid_runtime,
)
from infrastructure_role_transition import (
    InfrastructureRoleTransitionError,
    promote_controller_to_hybrid,
)
from placement_status_repository import PlacementStatusRepository
from registry_repository import InfrastructureIdentityConflict, RegistryRepository


def _require_admin(user: dict[str, Any] | None) -> None:
    if not user or str(user.get("role") or "").strip().lower() != "admin":
        raise PermissionError("admin role required")


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return normalized or "local"


def local_role_status(
    backend,
    *,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Return persisted local role plus runtime/placement readiness."""
    effective_node = str(node_id or socket.gethostname()).strip()
    if not effective_node:
        raise ValueError("node_id is required")

    repository = RegistryRepository(backend)
    repository.initialize()
    ph = repository.dialect.placeholder
    with repository.transaction() as session:
        node_row = session.execute(
            f"SELECT id,name,role,status FROM nodes WHERE id={ph}",
            (effective_node,),
        ).fetchone()
        if node_row is None:
            raise ValueError(f"Node {effective_node} does not exist")
        controller_row = session.execute(
            f"SELECT id,name,status FROM controllers WHERE node_id={ph}",
            (effective_node,),
        ).fetchone()
        agent_row = session.execute(
            f"SELECT id,controller_id,name,status FROM agents WHERE node_id={ph}",
            (effective_node,),
        ).fetchone()
        runtime_row = None
        if agent_row is not None:
            runtime_row = session.execute(
                "SELECT health_status,last_seen FROM agent_runtime_inventory "
                f"WHERE agent_id={ph}",
                (str(agent_row["id"]),),
            ).fetchone()

    node = dict(node_row)
    controller = None if controller_row is None else dict(controller_row)
    agent = None if agent_row is None else dict(agent_row)
    runtime = None if runtime_row is None else dict(runtime_row)
    placement = PlacementStatusRepository(backend).snapshot()

    return {
        "node_id": str(node["id"]),
        "node_name": str(node["name"]),
        "role": str(node["role"]),
        "node_status": str(node["status"]),
        "controller_id": None if controller is None else str(controller["id"]),
        "controller_status": None if controller is None else str(controller["status"]),
        "agent_id": None if agent is None else str(agent["id"]),
        "agent_status": None if agent is None else str(agent["status"]),
        "health_status": None if runtime is None else str(runtime["health_status"]),
        "last_seen": None if runtime is None else runtime["last_seen"],
        "placement_ready": bool(placement.get("placement_ready")),
        "placement_reason": placement.get("placement_reason"),
        "placement_reasons": list(placement.get("placement_reasons") or []),
    }


def promote_local_controller_for_user(
    user: dict[str, Any] | None,
    backend,
    root: Path,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Promote this Controller host to Hybrid and reconcile its local Agent."""
    _require_admin(user)
    data = payload if isinstance(payload, dict) else {}
    requested_role = str(data.get("role") or "").strip().lower()
    if requested_role != "hybrid":
        raise ValueError("only controller -> hybrid is supported")

    node_id = str(data.get("node_id") or socket.gethostname()).strip()
    if not node_id:
        raise ValueError("node_id is required")

    before = local_role_status(backend, node_id=node_id)
    if before.get("role") not in {"controller", "hybrid"}:
        raise InfrastructureRoleTransitionError(
            f"Node {node_id} has role {before.get('role')}; only controller -> hybrid is supported"
        )
    controller_id = str(before.get("controller_id") or "").strip()
    if not controller_id:
        raise InfrastructureRoleTransitionError(
            f"Node {node_id} has no Controller identity"
        )

    slug = _slug(node_id)
    agent_id = str(data.get("agent_id") or f"agent-{slug}").strip()
    transition = promote_controller_to_hybrid(
        RegistryRepository(backend),
        node_id=node_id,
        controller_id=controller_id,
        agent_id=agent_id,
        agent_name=f"Agent {node_id}",
        region_id=f"region-local-{slug}",
        region_name="Local",
        datacenter_id=f"datacenter-local-{slug}",
        datacenter_name="Local Default",
    )

    try:
        reconciliation = reconcile_local_hybrid_runtime(
            RegistryRepository(backend),
            Path(root),
            node_id=node_id,
            agent_id=agent_id,
            hostname=socket.gethostname(),
        )
    except HybridLocalReconciliationError:
        raise
    except Exception as exc:
        raise HybridLocalReconciliationError(
            "persisted role promotion succeeded, but local reconciliation failed"
        ) from exc

    after = local_role_status(backend, node_id=node_id)
    return {
        **after,
        "transition": transition,
        "reconciliation": reconciliation,
    }


__all__ = [
    "InfrastructureIdentityConflict",
    "InfrastructureRoleTransitionError",
    "HybridLocalReconciliationError",
    "local_role_status",
    "promote_local_controller_for_user",
]
