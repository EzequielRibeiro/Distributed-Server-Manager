#!/usr/bin/env python3
"""Administrative CLI for distributed instance creation, provisioning and deletion."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
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
from core.catalog_runtime_paths import runtime_definition_files
from catalog_provisioning_resolver import resolve_catalog_provisioning
from customer_reference import resolve_customer_reference
from dashboard_repository import DashboardRepository
from instance_network import occupied_ports_provider_for_backend
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
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in runtime_definition_files(ROOT / "catalog" / "v2"):
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


def _runtime_selector(definition: dict[str, Any]) -> str:
    version = definition.get("version") if isinstance(definition.get("version"), dict) else {}
    for key in ("value", "build"):
        value = str(version.get(key) or "").strip()
        if value:
            return value
    if str(version.get("strategy") or "").strip().lower() == "dynamic":
        return "latest"
    return str(definition.get("variant") or definition.get("edition") or "stable").strip()


def _content_selection(definition: dict[str, Any], selector: str) -> dict[str, Any]:
    runtime_id = str(definition.get("id") or "").strip()
    if not runtime_id:
        raise ValueError("runtime definition has no id")
    catalog_cli = ROOT / "installer" / "catalog.sh"
    if not catalog_cli.is_file():
        raise RuntimeError("catalog runtime resolver is unavailable")
    completed = subprocess.run(
        [str(catalog_cli), "--json", "runtime", "prepare", runtime_id, selector],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "runtime resolution failed").strip()
        raise RuntimeError(detail[:2000])
    try:
        selection = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("catalog runtime resolver returned invalid JSON") from exc
    if not isinstance(selection, dict) or selection.get("kind") != "RuntimeSelection":
        raise RuntimeError("catalog runtime resolver returned an invalid selection")
    if str(selection.get("runtime_definition") or "") != runtime_id:
        raise RuntimeError("catalog runtime resolver returned a mismatched runtime")
    provider = str(selection.get("provider") or "").strip().lower()
    if not provider:
        raise RuntimeError("resolved runtime selection has no provider")
    if provider in {"http", "http-archive", "github"}:
        install = selection.get("install") if isinstance(selection.get("install"), dict) else {}
        asset = selection.get("asset") if isinstance(selection.get("asset"), dict) else {}
        url = str(asset.get("url") or install.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            raise RuntimeError("resolved HTTP runtime selection has no artifact URL")
    return selection


def _owner(repository: DashboardRepository, customer_id: Any, requested: str | None) -> str:
    if requested:
        return str(requested).strip()
    ph = repository.dialect.placeholder
    with repository.session() as session:
        row = session.execute(
            "SELECT username FROM dashboard_users "
            f"WHERE role='customer' AND customer_id={ph} AND active "
            "ORDER BY username LIMIT 1",
            (customer_id,),
        ).fetchone()
    return str(row["username"]) if row is not None else str(customer_id).lower()


def _configuration(definition: dict[str, Any]) -> dict[str, Any]:
    process = definition.get("process") if isinstance(definition.get("process"), dict) else {}
    return {
        "runtime_definition_id": definition.get("id"),
        "process_args": list(process.get("args") or []),
    }


def _contract_profile_configuration(
    contracts: list[dict[str, Any]], contract_id: str, game_id: str, configuration: dict[str, Any]
) -> dict[str, Any]:
    """Carry the contracted resource profile into Agent provisioning, not just metadata."""
    contract = next((item for item in contracts if str(item.get("id") or "") == contract_id), None)
    if contract is None:
        raise PermissionError("requested contract does not belong to this customer")
    if str(contract.get("game_id") or "").lower() != game_id:
        raise PermissionError("requested contract does not cover this game")
    if str(contract.get("status") or "").lower() != "active":
        raise PermissionError("requested contract is not active")
    selected = str(contract.get("resource_profile_id") or "").strip().lower()
    result = dict(configuration)
    if selected:
        result["resource_profile_id"] = selected
        result["allowed_resource_profiles"] = [selected]
    return result


def create_instance(args, *, backend=None) -> dict[str, Any]:
    backend = backend or backend_from_environment()
    backend.initialize()
    admin = AdminManagementRepository(backend)
    admin.initialize()
    dashboard = DashboardRepository(backend)
    dashboard.initialize()

    customer_reference = str(args.customer).strip()
    customer_id = resolve_customer_reference(customer_reference, public_only=True)
    game_id = str(args.game).strip().lower()
    definition = _runtime_definition(game_id, args.runtime)
    runtime_id = str(definition.get("id") or "").strip()
    if not runtime_id:
        raise ValueError("runtime definition has no id")
    selector = _runtime_selector(definition)
    selection = _content_selection(definition, selector)
    configuration = _contract_profile_configuration(
        dashboard.customer_contracts(customer_id), str(args.contract).strip(), game_id,
        _configuration(definition),
    )
    selection, configuration = resolve_catalog_provisioning(
        environment_id=runtime_id,
        selector=selector,
        selection=selection,
        configuration=configuration,
        root=ROOT,
    )

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
    owner = _owner(dashboard, customer_id, args.owner)
    instances_root = Path(os.environ.get("DSM_INSTANCES_ROOT", str(ROOT / "instances")))

    created = dashboard.create_customer_instance(
        customer_id=customer_id,
        username=owner,
        game=game_id,
        runtime_id=runtime_id,
        edition=str(definition.get("edition") or "default"),
        variant=(None if definition.get("variant") is None else str(definition.get("variant"))),
        version=str(selection.get("version") or definition.get("variant") or "current"),
        build=str(selection.get("build") or ""),
        contract_id=str(args.contract).strip(),
        resource_profile_id=configuration.get("resource_profile_id"),
        selected_agent_id=str(placement["agent_id"]),
        instances_root=instances_root,
        network_profile=(definition.get("network") if isinstance(definition.get("network"), dict) else None),
        occupied_ports_provider=occupied_ports_provider_for_backend(backend),
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
            selector=selector,
            selection=selection,
            configuration=configuration,
            desired_state=str(args.desired_state),
            requested_by="cap-cli",
        )
    except Exception:
        dashboard.delete_instance(str(created["instance_id"]))
        raise

    return {
        "instance_id": created["instance_id"],
        "name": created["name"],
        "customer_id": customer_id,
        "customer_code": customer_reference.upper(),
        "contract_id": created["contract_id"],
        "game_id": game_id,
        "runtime_id": runtime_id,
        "runtime_version": selection.get("version"),
        "runtime_build": selection.get("build"),
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
