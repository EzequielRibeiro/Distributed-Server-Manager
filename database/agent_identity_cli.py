#!/usr/bin/env python3
"""Administrative CLI for Agent physical host identity."""
from __future__ import annotations

import argparse
import json
import sys

from agent_identity_admin_repository import (
    AgentIdentityAdminRepository,
    AgentIdentityRebindConflict,
)
from runtime_backend import backend_from_environment


def _print(value, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cap agent identity")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="Show the Agent host identity binding")
    show.add_argument("agent_id")
    show.add_argument("--json", action="store_true")

    incidents = sub.add_parser("incidents", help="List host identity collision incidents")
    incidents.add_argument("agent_id")
    incidents.add_argument("--limit", type=int, default=100)
    incidents.add_argument("--json", action="store_true")

    rebind = sub.add_parser("rebind", help="Explicitly bind an Agent to a new physical host identity")
    rebind.add_argument("agent_id")
    rebind.add_argument("--expected", required=True, dest="expected_identity")
    rebind.add_argument("--new", required=True, dest="new_identity")
    rebind.add_argument("--reason", required=True)
    rebind.add_argument("--actor", required=True)
    rebind.add_argument("--yes", action="store_true")
    rebind.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = AgentIdentityAdminRepository(backend_from_environment())
    try:
        if args.command == "show":
            _print(repo.show(args.agent_id), as_json=args.json)
            return 0
        if args.command == "incidents":
            _print(repo.incidents_history(args.agent_id, limit=args.limit), as_json=args.json)
            return 0
        if args.command == "rebind":
            if not args.yes:
                raise ValueError("rebind requires --yes")
            result = repo.rebind(
                args.agent_id,
                expected_identity=args.expected_identity,
                new_identity=args.new_identity,
                reason=args.reason,
                actor=args.actor,
            )
            _print(result, as_json=args.json)
            return 0
    except AgentIdentityRebindConflict as exc:
        print(f"CONFLICT: {exc}", file=sys.stderr)
        return 3
    except (ValueError, LookupError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
