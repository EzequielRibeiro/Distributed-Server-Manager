#!/usr/bin/env python3
"""Controller CLI for querying Universal Observability."""

from __future__ import annotations

import argparse
import json

from observability_repository import ObservabilityRepository
from runtime_backend import backend_from_environment


def _repo() -> ObservabilityRepository:
    repo = ObservabilityRepository(backend_from_environment())
    repo.initialize()
    return repo


def _filters(args):
    return {
        "agent_id": args.agent,
        "instance_id": args.instance,
        "metric_name": args.metric,
        "limit": args.limit,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cap observe")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("latest", "history", "summary"):
        item = sub.add_parser(name)
        item.add_argument("--agent")
        item.add_argument("--instance")
        item.add_argument("--metric")
        item.add_argument("--limit", type=int, default=500)
        if name in {"history", "summary"}:
            item.add_argument("--since")
            item.add_argument("--until")
        item.add_argument("--json", action="store_true")
    prune = sub.add_parser("prune")
    prune.add_argument("--before", required=True)
    prune.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    repo = _repo()
    if args.command == "prune":
        if not args.yes:
            parser.error("prune requires --yes")
        count = repo.prune_before(args.before)
        print(json.dumps({"deleted": count, "before": args.before}, sort_keys=True))
        return 0

    filters = _filters(args)
    if args.command == "latest":
        rows = repo.latest(**filters)
    elif args.command == "history":
        rows = repo.history(**filters, since=args.since, until=args.until)
    else:
        rows = repo.summary(**filters, since=args.since, until=args.until)
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            if args.command == "summary":
                print(f"{row['metric_name']:<40} avg={row['avg']:.3f} min={row['min']:.3f} max={row['max']:.3f} n={row['count']} {row['unit']}")
            else:
                print(f"{row.get('collected_at',''):<28} {row.get('metric_name',''):<40} {row.get('value')} {row.get('unit','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
