
#!/usr/bin/env python3
"""CLI for Controller-managed Agent port ranges."""

from __future__ import annotations

import argparse
import json

from agent_port_repository import (
    AgentPortRepository,
)
from runtime_backend import (
    backend_from_environment,
)


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Capivara DSM Agent port administration"
        )
    )

    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
    )

    subparsers = parser.add_subparsers(
        dest="action",
        required=True,
    )

    show = subparsers.add_parser(
        "show",
    )
    show.add_argument(
        "agent_id",
    )

    set_parser = subparsers.add_parser(
        "set",
    )
    set_parser.add_argument(
        "agent_id",
    )
    set_parser.add_argument(
        "start_port",
        type=int,
    )
    set_parser.add_argument(
        "end_port",
        type=int,
    )
    set_parser.add_argument(
        "--protocol",
        choices=[
            "tcp",
            "udp",
            "both",
        ],
        default="both",
    )
    set_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "administrative confirmation allowing "
            "existing reservations outside the new range"
        ),
    )

    check = subparsers.add_parser(
        "check",
    )
    check.add_argument(
        "agent_id",
    )

    return parser


def protocols(value: str) -> tuple[str, ...]:
    if value == "both":
        return (
            "tcp",
            "udp",
        )

    return (
        value,
    )


def print_summary(summary):
    agent = summary["agent"]

    print(
        f"Agent: {agent['id']} "
        f"({agent['name']})"
    )
    print(
        f"Node: {agent['node_id']}"
    )
    print(
        f"Status: {agent['status']}"
    )
    print()

    print("Ranges:")

    for item in summary["ranges"]:
        print(
            f"  {item['protocol'].upper()} "
            f"{item['start_port']}-"
            f"{item['end_port']} "
            f"reserved={item['reserved']} "
            f"available={item['available']} "
            f"usage={item['usage_pct']:.2f}%"
        )

    print()
    print(
        "Conflicts: "
        f"{summary['conflict_count']}"
    )


def main():
    args = build_parser().parse_args()

    backend = backend_from_environment()
    backend.initialize()

    repository = AgentPortRepository(
        backend
    )

    try:
        if args.action in {
            "show",
            "check",
        }:
            result = repository.summary(
                args.agent_id
            )

        else:
            result = repository.set_ranges(
                args.agent_id,
                protocols=protocols(
                    args.protocol
                ),
                start_port=args.start_port,
                end_port=args.end_port,
                force=args.force,
            )

            result["summary"] = (
                repository.summary(
                    args.agent_id
                )
            )

        if args.as_json:
            print(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

        elif args.action in {
            "show",
            "check",
        }:
            print_summary(
                result
            )

        else:
            print(
                "Agent port range updated."
            )
            print_summary(
                result["summary"]
            )

    except (
        ValueError,
        RuntimeError,
    ) as exc:
        raise SystemExit(
            f"error: {exc}"
        )


if __name__ == "__main__":
    main()
