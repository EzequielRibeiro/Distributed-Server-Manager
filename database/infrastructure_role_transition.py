#!/usr/bin/env python3
"""Safe infrastructure role transitions.

This module owns explicit transitions between persisted Capivara infrastructure
roles. It intentionally does not infer identities from unrelated records and does
not mutate customer, contract or instance ownership.
"""

from __future__ import annotations

from typing import Any

from registry_repository import InfrastructureIdentityConflict, RegistryRepository


class InfrastructureRoleTransitionError(ValueError):
    """Raised when a requested infrastructure role transition is unsafe."""


def _required(value: str | None, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise InfrastructureRoleTransitionError(f"{label} is required")
    return normalized


def promote_controller_to_hybrid(
    repository: RegistryRepository,
    *,
    node_id: str,
    controller_id: str,
    agent_id: str,
    agent_name: str,
    region_id: str,
    region_name: str,
    datacenter_id: str,
    datacenter_name: str,
) -> dict[str, Any]:
    """Promote one existing Controller node to Hybrid without replacing identity.

    Safety guarantees:
    - the existing Node and Controller IDs are preserved;
    - only ``controller -> hybrid`` (or idempotent ``hybrid -> hybrid``) is allowed;
    - an Agent already bound to the node must match the requested identity;
    - Controller/customer/contract/instance ownership is not rewritten;
    - local Region/Datacenter/Agent Location records are created only when absent;
    - the whole database mutation is atomic.

    Runtime inventory, heartbeat, credentials and local ``agent.conf`` are
    intentionally outside this database transaction and must be reconciled by the
    caller after this identity transition succeeds.
    """

    node_id = _required(node_id, "node_id")
    controller_id = _required(controller_id, "controller_id")
    agent_id = _required(agent_id, "agent_id")
    agent_name = _required(agent_name, "agent_name")
    region_id = _required(region_id, "region_id")
    region_name = _required(region_name, "region_name")
    datacenter_id = _required(datacenter_id, "datacenter_id")
    datacenter_name = _required(datacenter_name, "datacenter_name")

    repository.initialize()
    ph = repository.dialect.placeholder

    with repository.transaction() as session:
        node_row = session.execute(
            f"SELECT id,name,role,status FROM nodes WHERE id={ph}",
            (node_id,),
        ).fetchone()
        if node_row is None:
            raise InfrastructureRoleTransitionError(
                f"Node {node_id} does not exist; refusing to fabricate a Controller identity"
            )

        node = dict(node_row)
        current_role = str(node["role"]).strip().lower()
        if current_role not in {"controller", "hybrid"}:
            raise InfrastructureRoleTransitionError(
                f"Node {node_id} has role {current_role}; only controller -> hybrid is supported"
            )

        controller_row = session.execute(
            f"SELECT id,node_id,name,status FROM controllers WHERE id={ph}",
            (controller_id,),
        ).fetchone()
        if controller_row is None:
            raise InfrastructureRoleTransitionError(
                f"Controller {controller_id} does not exist"
            )
        controller = dict(controller_row)
        if str(controller["node_id"]) != node_id:
            raise InfrastructureRoleTransitionError(
                f"Controller {controller_id} belongs to node {controller['node_id']}"
            )

        agent_by_id_row = session.execute(
            f"SELECT id,controller_id,node_id,name,status FROM agents WHERE id={ph}",
            (agent_id,),
        ).fetchone()
        agent_by_node_row = session.execute(
            f"SELECT id,controller_id,node_id,name,status FROM agents WHERE node_id={ph}",
            (node_id,),
        ).fetchone()

        agent_by_id = None if agent_by_id_row is None else dict(agent_by_id_row)
        agent_by_node = None if agent_by_node_row is None else dict(agent_by_node_row)

        if agent_by_id is not None and (
            str(agent_by_id["controller_id"]) != controller_id
            or str(agent_by_id["node_id"]) != node_id
        ):
            raise InfrastructureIdentityConflict(
                f"Agent {agent_id} already belongs to another Controller/Node"
            )
        if agent_by_node is not None and str(agent_by_node["id"]) != agent_id:
            raise InfrastructureIdentityConflict(
                f"Node {node_id} already belongs to Agent {agent_by_node['id']}"
            )

        promoted = current_role == "controller"
        if promoted:
            session.execute(
                f"UPDATE nodes SET role={ph} WHERE id={ph}",
                ("hybrid", node_id),
            )

        agent = agent_by_id or agent_by_node
        agent_created = agent is None
        if agent_created:
            session.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES "
                f"({repository.dialect.parameters(5)})",
                (agent_id, controller_id, node_id, agent_name, "active"),
            )
            agent_status = "active"
        else:
            agent_status = str(agent["status"])

        region_row = session.execute(
            f"SELECT id,status FROM regions WHERE id={ph}",
            (region_id,),
        ).fetchone()
        if region_row is None:
            session.execute(
                "INSERT INTO regions(id,name,status) VALUES "
                f"({repository.dialect.parameters(3)})",
                (region_id, region_name, "active"),
            )
            region_status = "active"
        else:
            region_status = str(region_row["status"])

        datacenter_row = session.execute(
            f"SELECT id,region_id,status FROM datacenters WHERE id={ph}",
            (datacenter_id,),
        ).fetchone()
        if datacenter_row is None:
            session.execute(
                "INSERT INTO datacenters(id,region_id,name,status) VALUES "
                f"({repository.dialect.parameters(4)})",
                (datacenter_id, region_id, datacenter_name, "active"),
            )
            datacenter_status = "active"
        else:
            if str(datacenter_row["region_id"]) != region_id:
                raise InfrastructureIdentityConflict(
                    f"Datacenter {datacenter_id} belongs to another Region"
                )
            datacenter_status = str(datacenter_row["status"])

        location_row = session.execute(
            f"SELECT agent_id,datacenter_id,status FROM agent_locations WHERE agent_id={ph}",
            (agent_id,),
        ).fetchone()
        if location_row is None:
            session.execute(
                "INSERT INTO agent_locations(agent_id,datacenter_id,status) VALUES "
                f"({repository.dialect.parameters(3)})",
                (agent_id, datacenter_id, "active"),
            )
            location_status = "active"
        else:
            if str(location_row["datacenter_id"]) != datacenter_id:
                raise InfrastructureIdentityConflict(
                    f"Agent {agent_id} already belongs to another Datacenter"
                )
            location_status = str(location_row["status"])

        topology_ready = all(
            str(status).strip().lower() == "active"
            for status in (region_status, datacenter_status, location_status)
        )
        placement_identity_ready = (
            str(controller["status"]).strip().lower() == "active"
            and str(agent_status).strip().lower() == "active"
            and topology_ready
        )

        return {
            "transition": "controller_to_hybrid",
            "changed": promoted or agent_created,
            "node_id": node_id,
            "previous_role": current_role,
            "node_role": "hybrid",
            "controller_id": controller_id,
            "controller_status": str(controller["status"]),
            "agent_id": agent_id,
            "agent_status": agent_status,
            "agent_created": agent_created,
            "region_id": region_id,
            "datacenter_id": datacenter_id,
            "topology_state": "ready" if topology_ready else "partial",
            "placement_identity_ready": placement_identity_ready,
            "runtime_reconciliation_required": True,
        }


def demote_hybrid_to_controller(
    repository: RegistryRepository,
    *,
    node_id: str,
    controller_id: str,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Remove the local Hybrid Agent while preserving Node/Controller identity.

    This is the inverse persisted-identity transition of
    :func:`promote_controller_to_hybrid`.  It never deletes the shared Node or
    Controller.  A ``controller`` node without a local Agent is treated as an
    already-converged idempotent result.

    Runtime/config cleanup remains an explicit caller responsibility, just as it
    does for promotion.
    """

    node_id = _required(node_id, "node_id")
    controller_id = _required(controller_id, "controller_id")
    expected_agent_id = str(agent_id or "").strip() or None

    repository.initialize()
    ph = repository.dialect.placeholder

    with repository.transaction() as session:
        node_row = session.execute(
            f"SELECT id,name,role,status FROM nodes WHERE id={ph}",
            (node_id,),
        ).fetchone()
        if node_row is None:
            raise InfrastructureRoleTransitionError(f"Node {node_id} does not exist")
        node = dict(node_row)
        current_role = str(node["role"]).strip().lower()
        if current_role not in {"controller", "hybrid"}:
            raise InfrastructureRoleTransitionError(
                f"Node {node_id} has role {current_role}; only hybrid -> controller is supported"
            )

        controller_row = session.execute(
            f"SELECT id,node_id,name,status FROM controllers WHERE id={ph}",
            (controller_id,),
        ).fetchone()
        if controller_row is None:
            raise InfrastructureRoleTransitionError(f"Controller {controller_id} does not exist")
        controller = dict(controller_row)
        if str(controller["node_id"]) != node_id:
            raise InfrastructureRoleTransitionError(
                f"Controller {controller_id} belongs to node {controller['node_id']}"
            )

        agent_row = session.execute(
            f"SELECT id,controller_id,node_id,name,status FROM agents WHERE node_id={ph}",
            (node_id,),
        ).fetchone()
        agent = None if agent_row is None else dict(agent_row)

        if current_role == "controller":
            if agent is not None:
                raise InfrastructureRoleTransitionError(
                    f"Controller node {node_id} still owns Agent {agent['id']}; refusing ambiguous cleanup"
                )
            return {
                "transition": "hybrid_to_controller",
                "changed": False,
                "node_id": node_id,
                "previous_role": "controller",
                "node_role": "controller",
                "controller_id": controller_id,
                "controller_status": str(controller["status"]),
                "agent_id": expected_agent_id,
                "agent_removed": False,
                "runtime_reconciliation_required": False,
            }

        if agent is not None:
            actual_agent_id = str(agent["id"])
            if str(agent["controller_id"]) != controller_id:
                raise InfrastructureIdentityConflict(
                    f"Local Agent {actual_agent_id} belongs to another Controller"
                )
            if expected_agent_id is not None and actual_agent_id != expected_agent_id:
                raise InfrastructureIdentityConflict(
                    f"Node {node_id} belongs to Agent {actual_agent_id}, not {expected_agent_id}"
                )

            instances = session.execute(
                f"SELECT id FROM instances WHERE node_id={ph} ORDER BY id",
                (node_id,),
            ).fetchall()
            if instances:
                raise InfrastructureRoleTransitionError(
                    f"Hybrid Agent {actual_agent_id} has {len(instances)} instance(s); migrate or remove them before demotion"
                )

            session.execute(
                f"DELETE FROM agent_locations WHERE agent_id={ph}",
                (actual_agent_id,),
            )
            session.execute(
                f"DELETE FROM agents WHERE id={ph}",
                (actual_agent_id,),
            )
            removed_agent_id = actual_agent_id
            agent_removed = True
        else:
            removed_agent_id = expected_agent_id
            agent_removed = False

        session.execute(
            f"UPDATE nodes SET role={ph} WHERE id={ph}",
            ("controller", node_id),
        )

        return {
            "transition": "hybrid_to_controller",
            "changed": True,
            "node_id": node_id,
            "previous_role": "hybrid",
            "node_role": "controller",
            "controller_id": controller_id,
            "controller_status": str(controller["status"]),
            "agent_id": removed_agent_id,
            "agent_removed": agent_removed,
            "runtime_reconciliation_required": True,
        }


__all__ = [
    "InfrastructureRoleTransitionError",
    "promote_controller_to_hybrid",
    "demote_hybrid_to_controller",
]
