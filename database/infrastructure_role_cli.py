#!/usr/bin/env python3
"""CLI boundary for safe infrastructure role transitions."""

from __future__ import annotations

import argparse
import json
import re
import socket
from typing import Any

from infrastructure_role_transition import (
    InfrastructureRoleTransitionError,
    promote_controller_to_hybrid,
)
from registry_repository import InfrastructureIdentityConflict, RegistryRepository
from runtime_backend import backend_from_environment


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return normalized or "local"


def _repository() -> RegistryRepository:
    return RegistryRepository(backend_from_environment())


def role_status(repository: RegistryRepository, *, node_id: str) -> dict[str, Any]:
    repository.initialize()
    ph = repository.dialect.placeholder
    with repository.transaction() as session:
        node_row = session.execute(
            f"SELECT id,name,role,status FROM nodes WHERE id={ph}",
            (node_id,),
        ).fetchone()
        if node_row is None:
            raise InfrastructureRoleTransitionError(f"Node {node_id} does not exist")

        controller_row = session.execute(
            f"SELECT id,name,status FROM controllers WHERE node_id={ph}",
            (node_id,),
        ).fetchone()
        agent_row = session.execute(
            f"SELECT id,controller_id,name,status FROM agents WHERE node_id={ph}",
            (node_id,),
        ).fetchone()

    node = dict(node_row)
    controller = None if controller_row is None else dict(controller_row)
    agent = None if agent_row is None else dict(agent_row)
    return {
        "node_id": str(node["id"]),
        "node_name": str(node["name"]),
        "role": str(node["role"]),
        "node_status": str(node["status"]),
        "controller_id": None if controller is None else str(controller["id"]),
        "controller_status": None if controller is None else str(controller["status"]),
        "agent_id": None if agent is None else str(agent["id"]),
        "agent_status": None if agent is None else str(agent["status"]),
    }


def _controller_id_for_node(
    repository: RegistryRepository,
    *,
    node_id: str,
    requested: str | None,
) -> str:
    if requested:
        return str(requested).strip()
    status = role_status(repository, node_id=node_id)
    controller_id = status.get("controller_id")
    if not controller_id:
        raise InfrastructureRoleTransitionError(
            f"Node {node_id} has no Controller identity"
        )
    return str(controller_id)


def promote_local_controller(
    repository: RegistryRepository,
    *,
    node_id: str,
    controller_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    slug = _slug(node_id)
    effective_controller = _controller_id_for_node(
        repository,
        node_id=node_id,
        requested=controller_id,
    )
    effective_agent = str(agent_id or f"agent-{slug}").strip()
    return promote_controller_to_hybrid(
        repository,
        node_id=node_id,
        controller_id=effective_controller,
        agent_id=effective_agent,
        agent_name=f"Agent {node_id}",
        region_id=f"region-local-{slug}",
        region_name="Local",
        datacenter_id=f"datacenter-local-{slug}",
        datacenter_name="Local Default",
    )


def _print_human(payload: dict[str, Any]) -> None:
    fields = (
        ("Node", payload.get("node_id")),
        ("Role", payload.get("node_role") or payload.get("role")),
        ("Controller", payload.get("controller_id") or "none"),
        ("Agent", payload.get("agent_id") or "none"),
        ("Agent status", payload.get("agent_status") or "none"),
        ("Topology", payload.get("topology_state") or "n/a"),
    )
    for label, value in fields:
        print(f"{label:<14}: {value}")
    if "changed" in payload:
        print(f"Changed       : {'yes' if payload.get('changed') else 'no'}")
        print(
            "Runtime sync  : "
            + ("required" if payload.get("runtime_reconciliation_required") else "not required")
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capivara infrastructure role administration")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="show the persisted role of a local Node")
    show.add_argument("--node-id", default=socket.gethostname())
    show.add_argument("--json", action="store_true")

    set_parser = sub.add_parser("set", help="perform an explicit safe role transition")
    set_parser.add_argument("role", choices=("hybrid",))
    set_parser.add_argument("--node-id", default=socket.gethostname())
    set_parser.add_argument("--controller-id")
    set_parser.add_argument("--agent-id")
    set_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repository = _repository()
    try:
        if args.command == "show":
            payload = role_status(repository, node_id=str(args.node_id).strip())
        else:
            payload = promote_local_controller(
                repository,
                node_id=str(args.node_id).strip(),
                controller_id=args.controller_id,
                agent_id=args.agent_id,
            )
    except (InfrastructureRoleTransitionError, InfrastructureIdentityConflict) as exc:
        parser.exit(2, f"Erro: {exc}\n")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
