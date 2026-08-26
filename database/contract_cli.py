#!/usr/bin/env python3
"""Administrative CLI for Capivara service contracts."""

from __future__ import annotations

import argparse
import json

from admin_cli_auth import require_admin
from admin_management_repository import AdminManagementRepository
from runtime_backend import backend_from_environment


def build_parser():
    parser = argparse.ArgumentParser(description="Capivara DSM contract administration")
    parser.add_argument("--json", action="store_true", dest="as_json")
    subparsers = parser.add_subparsers(dest="action", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--customer", required=True)
    create.add_argument("--game", required=True)
    create.add_argument("--instances", type=int, default=1)
    create.add_argument("--id", dest="contract_id")
    create.add_argument("--ends-at")

    delete = subparsers.add_parser("delete")
    delete.add_argument("--contract", required=True)
    delete.add_argument("--admin", required=True, help="dashboard administrator username")
    delete.add_argument("--yes", action="store_true", help="confirm destructive cascading deletion")
    return parser


def _delete(args, backend, repository):
    # Deletion needs the Agent runtime queue, which imports Controller-root
    # modules. Keep that dependency out of the create path so `cap contract
    # create` only loads the persistence code it actually needs.
    from agent_instance_runtime_repository import AgentInstanceRuntimeRepository

    if not args.yes:
        raise ValueError("contract deletion requires --yes")
    actor = require_admin(backend, args.admin)
    state = repository.begin_contract_delete(args.contract)
    commands = []
    queue = AgentInstanceRuntimeRepository(backend)
    queue.initialize()
    for item in state.get("instances", []):
        command = queue.enqueue(
            agent_id=item["agent_id"],
            instance_id=item["instance_id"],
            action="remove",
            requested_by=str(actor["username"]),
        )
        commands.append({
            "instance_id": item["instance_id"],
            "agent_id": item["agent_id"],
            "command_id": command["command_id"],
            "status": command["status"],
        })
    return {**state, "requested_by": actor["username"], "remove_commands": commands}


def main() -> int:
    args = build_parser().parse_args()
    backend = backend_from_environment()
    backend.initialize()
    repository = AdminManagementRepository(backend)
    try:
        if args.action == "create":
            result = repository.create_contract(
                customer_id=args.customer,
                game_id=args.game,
                instance_limit=args.instances,
                contract_id=args.contract_id,
                ends_at=args.ends_at,
            )
        else:
            result = _delete(args, backend, repository)
    except (ValueError, RuntimeError, PermissionError) as exc:
        raise SystemExit(f"error: {exc}") from exc

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    elif args.action == "create":
        print(f"Contract created: {result['id']}")
        print(f"Customer: {result['customer_id']}")
        print(f"Game: {result['game_id']}")
        print(f"Instance limit: {result['instance_limit']}")
    elif result["status"] == "deleted":
        print(f"Contract deleted: {result['contract_id']}")
        print("No instances were bound to this contract.")
    else:
        print(f"Contract deletion started: {result['contract_id']}")
        print(f"Instances scheduled for removal: {len(result['remove_commands'])}")
        print("The contract is deleted after every Agent confirms instance removal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
