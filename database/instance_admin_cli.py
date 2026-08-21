#!/usr/bin/env python3
"""Administrative CLI for distributed instance creation, provisioning and deletion."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from admin_cli_auth import require_admin
from admin_management_repository import AdminManagementRepository
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from agent_runtime_repository import AgentRuntimeRepository
from dashboard_repository import DashboardRepository
from placement_errors import PlacementUnavailable
from placement_service import choose_agent_for_instance
from core.placement_requirements import requirements_for_instance
from runtime_backend import backend_from_environment


def build_parser():
    parser = argparse.ArgumentParser(description="Capivara DSM distributed instance administration")
    parser.add_argument("--json", action="store_true", dest="as_json")
    subparsers = parser.add_subparsers(dest="action", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--customer", required=True)
    create.add_argument("--contract", required=True)
    create.add_argument("--game", required=True)
    create.add_argument("--agent", required=True, help="Agent ID or advertised address")
    create.add_argument("--runtime")
    create.add_argument("--name")
    create.add_argument("--owner")
    create.add_argument("--desired-state", choices=("running", "stopped"), default="running")

    delete = subparsers.add_parser("delete")
    delete.add_argument("--instance", required=True)
    delete.add_argument("--admin", required=True, help="dashboard administrator username")
    delete.add_argument("--yes", action="store_true", help="confirm destructive deletion")
    return parser


def _runtime_candidates(game_id: str) -> list[tuple[Path, dict[str, Any]]]:
    directory = ROOT / "catalog" / "v2" / "runtimes" / game_id
    result: list[tuple[Path, dict[str, Any]]] = []
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and str(payload.get("game") or "").lower() == game_id:
            result.append((path, payload))
    return result


def _runtime_definition(game_id: str, runtime_id: str | None) -> dict[str, Any]:
    game_id = str(game_id or "").strip().lower()
    candidates = _runtime_candidates(game_id)
    if runtime_id:
        runtime_id = str(runtime_id).strip()
        for _, payload in candidates:
            if str(payload.get("id") or "") == runtime_id:
                return payload
        raise ValueError(f"runtime not found: {runtime_id}")
    if not candidates:
        raise ValueError(f"no runtime is registered for game: {game_id}")
    if len(candidates) != 1:
        available = ", ".join(str(item[1].get("id")) for item in candidates)
        raise ValueError(f"multiple runtimes are available; use --runtime ({available})")
    return candidates[0][1]


def _remote_occupied_ports(snapshot: dict[str, Any]):
    network = snapshot.get("network") if isinstance(snapshot.get("network"), dict) else {}
    values = {
        "tcp": {int(value) for value in network.get("tcp_listen", []) if isinstance(value, int)},
        "udp": {int(value) for value in network.get("udp_listen", []) if isinstance(value, int)},
    }

    def provider(agent_id: str, node_id: str, protocol: str, start_port: int, end_port: int) -> set[int]:
        del agent_id, node_id
        return {
            port for port in values.get(str(protocol).lower(), set())
            if int(start_port) <= port <= int(end_port)
        }

    return provider


def _content_selection(definition: dict[str, Any]) -> dict[str, Any]:
    artifact = definition.get("artifact") if isinstance(definition.get("artifact"), dict) else {}
    provider = str(artifact.get("provider") or "").strip().lower()
    if not provider:
        raise ValueError("runtime artifact provider is missing")
    version = definition.get("version") if isinstance(definition.get("version"), dict) else {}
    installation = definition.get("installation") if isinstance(definition.get("installation"), dict) else {}
    selection: dict[str, Any] = {
        "game": str(definition.get("game") or ""),
        "provider": provider,
        "version": version.get("value") or definition.get("variant"),
        "auth": artifact.get("auth") or "anonymous",
    }
    directory = str(installation.get("directory") or "").strip()
    if directory:
        selection["install_dir"] = Path(directory).name
    install = {
        key: value for key, value in artifact.items()
        if key not in {"provider", "auth"} and value is not None
    }
    if install:
        selection["install"] = install
    return selection


def _owner(repository: DashboardRepository, customer_id: str, requested: str | None) -> str:
    if requested:
        return str(requested).strip()
    ph = repository.dialect.placeholder
    with repository.session() as session:
        row = session.execute(
            "SELECT username FROM dashboard_users "
            f"WHERE role='customer' AND scope_id={ph} AND active "
            "ORDER BY username LIMIT 1",
            (customer_id,),
        ).fetchone()
    return str(row["username"]) if row is not None else customer_id.lower()


def _configuration(definition: dict[str, Any]) -> dict[str, Any]:
    process = definition.get("process") if isinstance(definition.get("process"), dict) else {}
    return {
        "runtime_definition_id": definition.get("id"),
        "process_args": list(process.get("args") or []),
    }


def create_instance(args, *, backend=None) -> dict[str, Any]:
    backend = backend or backend_from_environment()
    backend.initialize()
    admin = AdminManagementRepository(backend)
    admin.initialize()
    dashboard = DashboardRepository(backend)
    dashboard.initialize()

    customer_id = str(args.customer).strip()
    game_id = str(args.game).strip().lower()
    definition = _runtime_definition(game_id, args.runtime)
    runtime_id = str(definition.get("id") or "").strip()
    if not runtime_id:
        raise ValueError("runtime definition has no id")

    controller_id = admin.customer_controller(customer_id)
    selected = admin.resolve_agent(controller_id, args.agent)
    selected_agent_id = str(selected["id"])

    requirements = requirements_for_instance(game_id=game_id, runtime_id=runtime_id)
    placement = choose_agent_for_instance(
        backend,
        controller_id=controller_id,
        requirements=requirements,
        required_agent_id=selected_agent_id,
    )

    runtime_repository = AgentRuntimeRepository(backend)
    snapshot = runtime_repository.snapshot(selected_agent_id)
    if str(snapshot.get("health_status") or "").lower() != "online":
        raise ValueError("selected Agent is not online")
    network = snapshot.get("network") if isinstance(snapshot.get("network"), dict) else {}
    if network.get("source") != "ss":
        raise ValueError("selected Agent has no current OS port inventory")

    version = definition.get("version") if isinstance(definition.get("version"), dict) else {}
    owner = _owner(dashboard, customer_id, args.owner)
    instances_root = Path(os.environ.get("DSM_INSTANCES_ROOT", str(ROOT / "instances")))

    created = dashboard.create_customer_instance(
        customer_id=customer_id,
        username=owner,
        game=game_id,
        runtime_id=runtime_id,
        edition=str(definition.get("edition") or "default"),
        variant=(None if definition.get("variant") is None else str(definition.get("variant"))),
        version=str(version.get("value") or definition.get("variant") or "current"),
        build=str(version.get("build") or ""),
        contract_id=str(args.contract).strip(),
        selected_agent_id=str(placement["agent_id"]),
        instances_root=instances_root,
        network_profile=(definition.get("network") if isinstance(definition.get("network"), dict) else None),
        occupied_ports_provider=_remote_occupied_ports(snapshot),
    )

    if args.name:
        requested_name = str(args.name).strip()
        if requested_name:
            with dashboard.session(transaction=True) as session:
                session.execute(
                    f"UPDATE instances SET name={dashboard.dialect.placeholder} "
                    f"WHERE id={dashboard.dialect.placeholder}",
                    (requested_name, created["instance_id"]),
                )
            created["name"] = requested_name

    try:
        provisioning = AgentInstanceProvisioningRepository(backend).enqueue(
            agent_id=str(created["agent_id"]),
            instance_id=str(created["instance_id"]),
            environment_id=runtime_id,
            selector=str(definition.get("variant") or definition.get("edition") or "stable"),
            selection=_content_selection(definition),
            configuration=_configuration(definition),
            desired_state=str(args.desired_state),
            requested_by="dsm-cli",
        )
    except Exception:
        dashboard.delete_instance(str(created["instance_id"]))
        raise

    return {
        "instance_id": created["instance_id"],
        "name": created["name"],
        "customer_id": customer_id,
        "contract_id": created["contract_id"],
        "game_id": game_id,
        "runtime_id": runtime_id,
        "agent_id": created["agent_id"],
        "agent_address": snapshot.get("address"),
        "node_id": created["node_id"],
        "ports": created.get("ports") or {},
        "desired_state": args.desired_state,
        "provisioning_id": provisioning["provisioning_id"],
        "provisioning_status": provisioning["status"],
    }


def delete_instance(args, *, backend=None) -> dict[str, Any]:
    if not args.yes:
        raise ValueError("instance deletion requires --yes")
    backend = backend or backend_from_environment()
    backend.initialize()
    actor = require_admin(backend, args.admin)
    repository = AdminManagementRepository(backend)
    state = repository.begin_instance_delete(args.instance)
    queue = AgentInstanceRuntimeRepository(backend)
    queue.initialize()
    try:
        command = queue.enqueue(
            agent_id=state["agent_id"],
            instance_id=state["instance_id"],
            action="remove",
            requested_by=str(actor["username"]),
        )
    except Exception:
        repository.restore_instance_status(state["instance_id"], state["previous_status"])
        raise
    return {
        **state,
        "requested_by": actor["username"],
        "command_id": command["command_id"],
        "command_status": command["status"],
    }


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = create_instance(args) if args.action == "create" else delete_instance(args)
    except PlacementUnavailable as exc:
        raise SystemExit(f"error: placement unavailable ({exc.reason})") from exc
    except (ValueError, RuntimeError, PermissionError, KeyError) as exc:
        raise SystemExit(f"error: {exc}") from exc

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    elif args.action == "create":
        print(f"Instance created: {result['instance_id']}")
        print(f"Agent: {result['agent_id']} ({result.get('agent_address') or 'address unavailable'})")
        print(f"Runtime: {result['runtime_id']}")
        print(f"Ports: {result['ports']}")
        print(f"Provisioning queued: {result['provisioning_id']}")
        print(f"Desired state: {result['desired_state']}")
    else:
        print(f"Instance deletion started: {result['instance_id']}")
        print(f"Agent: {result['agent_id']}")
        print(f"Removal command: {result['command_id']}")
        print("The database record and port reservations are released after Agent confirmation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
