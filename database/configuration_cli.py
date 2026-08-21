#!/usr/bin/env python3
"""Controller CLI for Universal Configuration Platform."""

from __future__ import annotations

import argparse
import json
import sys

from configuration_repository import ConfigurationRepository
from runtime_backend import backend_from_environment
from universal_event_repository import UniversalEventRepository


def _repo():
    backend = backend_from_environment()
    repo = ConfigurationRepository(backend)
    repo.initialize()
    return backend, repo


def _scope(parser):
    parser.add_argument("--scope", dest="scope_type", choices=("global", "agent", "instance"), required=True)
    parser.add_argument("--scope-id")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cap config-store")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list")
    listing.add_argument("--scope", dest="scope_type", choices=("global", "agent", "instance"))
    listing.add_argument("--scope-id")
    listing.add_argument("--namespace")
    listing.add_argument("--limit", type=int, default=200)
    listing.add_argument("--json", action="store_true")

    get = sub.add_parser("get")
    _scope(get)
    get.add_argument("namespace")
    get.add_argument("--json", action="store_true")

    put = sub.add_parser("set")
    _scope(put)
    put.add_argument("namespace")
    put.add_argument("--value-json", required=True)
    put.add_argument("--actor", default="cli")
    put.add_argument("--json", action="store_true")

    history = sub.add_parser("history")
    history.add_argument("configuration_id")
    history.add_argument("--json", action="store_true")

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--agent", required=True)
    resolve.add_argument("--instance")
    resolve.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    backend, repo = _repo()

    if args.command == "list":
        rows = repo.list_configurations(scope_type=args.scope_type, scope_id=args.scope_id, namespace=args.namespace, limit=args.limit)
        if args.json:
            print(json.dumps(rows, indent=2, sort_keys=True))
        else:
            for row in rows:
                print(f"{row['scope_type']:<8} {str(row.get('scope_id') or '*'):<24} {row['namespace']:<30} rev={row['revision']} {row['checksum'][:12]}")
        return 0

    if args.command == "get":
        row = repo.get(scope_type=args.scope_type, scope_id=args.scope_id, namespace=args.namespace)
        if row is None:
            print("Configuração não encontrada.", file=sys.stderr)
            return 1
        print(json.dumps(row, indent=2, sort_keys=True) if args.json else json.dumps(row["value"], indent=2, sort_keys=True))
        return 0

    if args.command == "set":
        try:
            value = json.loads(args.value_json)
        except json.JSONDecodeError as exc:
            print(f"--value-json inválido: {exc}", file=sys.stderr)
            return 2
        result = repo.put({"scope_type": args.scope_type, "scope_id": args.scope_id, "namespace": args.namespace, "value": value}, updated_by=args.actor)
        if result["changed"]:
            event_repo = UniversalEventRepository(backend)
            event_repo.initialize()
            event_repo.publish({
                "event_type": "CONFIGURATION_UPDATED",
                "source": "controller.configuration",
                "severity": "info",
                "actor_type": "cli",
                "actor_id": args.actor,
                "data": {
                    "configuration_id": result["configuration"]["configuration_id"],
                    "scope_type": args.scope_type,
                    "scope_id": args.scope_id,
                    "namespace": args.namespace,
                    "revision": result["configuration"]["revision"],
                    "checksum": result["configuration"]["checksum"],
                },
            })
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else f"Configuração {'atualizada' if result['changed'] else 'sem alterações'}: {result['configuration']['configuration_id']} rev={result['configuration']['revision']}")
        return 0

    if args.command == "history":
        rows = repo.history(args.configuration_id)
        print(json.dumps(rows, indent=2, sort_keys=True) if args.json else "\n".join(f"rev={r['revision']} {r['checksum'][:12]} {r.get('created_at','')}" for r in rows))
        return 0

    rows = repo.resolve_for_instance(args.agent, args.instance) if args.instance else repo.resolve_for_agent(args.agent)
    print(json.dumps(rows, indent=2, sort_keys=True) if args.json else "\n".join(f"{r['target_type']}={r['target_id']} {r['namespace']} {r['revision']}" for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
