#!/usr/bin/env python3
"""Administrative CLI for Capivara service contracts."""

from __future__ import annotations

import argparse
import json

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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    backend = backend_from_environment()
    backend.initialize()
    repository = AdminManagementRepository(backend)
    try:
        result = repository.create_contract(
            customer_id=args.customer,
            game_id=args.game,
            instance_limit=args.instances,
            contract_id=args.contract_id,
            ends_at=args.ends_at,
        )
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"Contract created: {result['id']}")
        print(f"Customer: {result['customer_id']}")
        print(f"Game: {result['game_id']}")
        print(f"Instance limit: {result['instance_limit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
