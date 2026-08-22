#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path


DATABASE_DIR = Path(__file__).resolve().parent

if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(DATABASE_DIR),
    )


from alert_repository import AlertRepository
from runtime_backend import backend_from_environment


def repository():
    return AlertRepository(
        backend_from_environment()
    )


def normalize_level(value):
    level = (
        str(value or "")
        .strip()
        .upper()
    )

    aliases = {
        "SUCCESS": "INFO",
        "OK": "INFO",
    }

    level = aliases.get(
        level,
        level,
    )

    if level not in {
        "INFO",
        "WARNING",
        "CRITICAL",
    }:
        raise ValueError(
            f"invalid alert level: {value}"
        )

    return level


def print_json(payload):
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def command_open(args):
    result = repository().open_alert(
        alert_id=args.id,
        rule_id=args.rule_id,
        level=normalize_level(
            args.level
        ),
        message=args.message,
        scope=args.scope,
        controller_id=args.controller_id,
        agent_id=args.agent_id,
        node_id=args.node_id,
        instance_id=args.instance_id,
    )

    print_json(result)


def command_ack(args):
    result = repository().acknowledge_alert(
        args.id,
    )

    print_json(result)


def command_resolve(args):
    result = repository().resolve_alert(
        args.id,
    )

    print_json(result)


def command_get(args):
    result = repository().get_alert(
        args.id,
    )

    print_json(result)


def command_active(args):
    result = repository().list_alerts(
        active_only=True,
    )

    print_json(result)


def command_count(args):
    result = repository().count_alerts(
        active_only=True,
    )

    print_json(
        {
            "count": result,
        }
    )


def command_history(args):
    if args.id:
        result = repository().alert_history(
            args.id,
        )
    else:
        result = repository().list_alerts(
        )

    print_json(result)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cap alerts",
        description=(
            "Capivara DSM Alert Store CLI"
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    open_parser = subparsers.add_parser(
        "open"
    )

    open_parser.add_argument(
        "--id",
        required=True,
    )

    open_parser.add_argument(
        "--rule-id",
        required=True,
    )

    open_parser.add_argument(
        "--level",
        required=True,
    )

    open_parser.add_argument(
        "--message",
        required=True,
    )

    open_parser.add_argument(
        "--scope",
        required=True,
    )

    open_parser.add_argument(
        "--controller-id",
        required=True,
    )

    open_parser.add_argument(
        "--agent-id",
    )

    open_parser.add_argument(
        "--node-id",
    )

    open_parser.add_argument(
        "--instance-id",
    )

    open_parser.set_defaults(
        handler=command_open
    )

    ack_parser = subparsers.add_parser(
        "ack"
    )

    ack_parser.add_argument(
        "id"
    )

    ack_parser.set_defaults(
        handler=command_ack
    )

    resolve_parser = subparsers.add_parser(
        "resolve"
    )

    resolve_parser.add_argument(
        "id"
    )

    resolve_parser.set_defaults(
        handler=command_resolve
    )

    get_parser = subparsers.add_parser(
        "get"
    )

    get_parser.add_argument(
        "id"
    )

    get_parser.set_defaults(
        handler=command_get
    )

    active_parser = subparsers.add_parser(
        "active"
    )

    active_parser.set_defaults(
        handler=command_active
    )

    count_parser = subparsers.add_parser(
        "count"
    )

    count_parser.set_defaults(
        handler=command_count
    )

    history_parser = subparsers.add_parser(
        "history"
    )

    history_parser.add_argument(
        "id",
        nargs="?",
    )

    history_parser.set_defaults(
        handler=command_history
    )

    return parser


def main():
    parser = build_parser()

    args = parser.parse_args()

    try:
        args.handler(
            args
        )

    except ValueError as exc:
        print_json(
            {
                "ok": False,
                "error": str(exc),
            }
        )

        return 2

    except Exception as exc:
        print_json(
            {
                "ok": False,
                "error": str(exc),
            }
        )

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
