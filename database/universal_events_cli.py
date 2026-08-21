#!/usr/bin/env python3
"""Controller CLI for querying and publishing Universal Events."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from runtime_backend import backend_from_environment
from universal_event_repository import UniversalEventRepository


def _print_event(event: dict[str, Any]) -> None:
    print(
        f"{event.get('occurred_at','')}  {event.get('severity','info'):<8} "
        f"{event.get('event_type',''):<32} {event.get('event_id','')}"
    )
    subject = []
    if event.get("agent_id"):
        subject.append(f"agent={event['agent_id']}")
    if event.get("instance_id"):
        subject.append(f"instance={event['instance_id']}")
    if subject:
        print("  " + " ".join(subject))


def _repository() -> UniversalEventRepository:
    repo = UniversalEventRepository(backend_from_environment())
    repo.initialize()
    return repo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cap events")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list")
    listing.add_argument("--type", dest="event_type")
    listing.add_argument("--agent", dest="agent_id")
    listing.add_argument("--instance", dest="instance_id")
    listing.add_argument("--severity")
    listing.add_argument("--correlation", dest="correlation_id")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--json", action="store_true")

    show = sub.add_parser("show")
    show.add_argument("event_id")
    show.add_argument("--json", action="store_true")

    publish = sub.add_parser("publish")
    publish.add_argument("event_type")
    publish.add_argument("--source", required=True)
    publish.add_argument("--source-id")
    publish.add_argument("--agent")
    publish.add_argument("--instance")
    publish.add_argument("--severity", default="info")
    publish.add_argument("--correlation")
    publish.add_argument("--actor-type")
    publish.add_argument("--actor-id")
    publish.add_argument("--data-json", default="{}")
    publish.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    repo = _repository()

    if args.command == "list":
        events = repo.list_events(
            limit=args.limit,
            event_type=args.event_type,
            agent_id=args.agent_id,
            instance_id=args.instance_id,
            severity=args.severity,
            correlation_id=args.correlation_id,
        )
        if args.json:
            print(json.dumps(events, indent=2, sort_keys=True))
        else:
            for event in events:
                _print_event(event)
        return 0

    if args.command == "show":
        event = repo.get(args.event_id)
        if event is None:
            print(f"Evento não encontrado: {args.event_id}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(event, indent=2, sort_keys=True))
        else:
            _print_event(event)
            print(json.dumps(event.get("data") or {}, indent=2, sort_keys=True))
        return 0

    try:
        data = json.loads(args.data_json)
    except json.JSONDecodeError as exc:
        print(f"--data-json inválido: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("--data-json deve conter um objeto JSON", file=sys.stderr)
        return 2
    result = repo.publish({
        "event_type": args.event_type,
        "source": args.source,
        "source_id": args.source_id,
        "agent_id": args.agent,
        "instance_id": args.instance,
        "severity": args.severity,
        "correlation_id": args.correlation,
        "actor_type": args.actor_type,
        "actor_id": args.actor_id,
        "data": data,
    })
    event = result["event"]
    if args.json:
        print(json.dumps({"created": result["created"], "event": event}, indent=2, sort_keys=True))
    else:
        print(f"Evento {'criado' if result['created'] else 'já existente'}: {event['event_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
