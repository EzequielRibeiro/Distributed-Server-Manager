#!/usr/bin/env python3
"""Controller CLI for Universal Smart Backup."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from backup_intelligence import PRESETS, apply_preset, preset_names
from backup_repository import BackupRepository
from runtime_backend import backend_from_environment


def repo():
    repository = BackupRepository(backend_from_environment())
    repository.initialize()
    return repository


def _print_health(value):
    if value.get("kind") == "CapivaraBackupFleetHealth":
        print(
            f"policies={value.get('count', 0)} "
            f"attention={value.get('attention_required', 0)} "
            f"counts={json.dumps(value.get('counts', {}), sort_keys=True)}"
        )
        for row in value.get("policies", []):
            print(
                f"{str(row.get('instance_id') or ''):<28} "
                f"{str(row.get('health') or ''):<10} "
                f"next={row.get('next_due_at') or '-'} "
                f"failures={row.get('consecutive_failures', 0)}"
            )
        return
    print(
        f"{str(value.get('instance_id') or ''):<28} "
        f"{str(value.get('health') or ''):<10} "
        f"last={value.get('last_success_at') or '-'} "
        f"next={value.get('next_due_at') or '-'} "
        f"failures={value.get('consecutive_failures', 0)}"
    )
    if value.get("recommendation"):
        print(value["recommendation"])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cap backup-store")
    sub = parser.add_subparsers(dest="command", required=True)

    policy = sub.add_parser("policy-set")
    policy.add_argument("--instance", required=True)
    policy.add_argument("--enabled", choices=("true", "false"), default="true")
    policy.add_argument("--mode", choices=("full", "config", "world", "custom"), default="full")
    policy.add_argument("--consistency", choices=("live", "quiesced", "stopped"), default="live")
    policy.add_argument("--compression", choices=("gzip", "none"), default="gzip")
    policy.add_argument("--interval", type=int, default=21600)
    policy.add_argument("--retention", type=int, default=7)
    policy.add_argument("--include-json", default="[]")
    policy.add_argument("--exclude-json", default="[]")
    policy.add_argument("--json", action="store_true")

    policies = sub.add_parser("policy-list")
    policies.add_argument("--agent")
    policies.add_argument("--json", action="store_true")

    history = sub.add_parser("history")
    history.add_argument("policy_id")
    history.add_argument("--json", action="store_true")

    jobs = sub.add_parser("jobs")
    jobs.add_argument("--instance")
    jobs.add_argument("--agent")
    jobs.add_argument("--status")
    jobs.add_argument("--json", action="store_true")

    preset_list = sub.add_parser("preset-list")
    preset_list.add_argument("--json", action="store_true")

    preset_apply = sub.add_parser("preset-apply")
    preset_apply.add_argument("--instance", required=True)
    preset_apply.add_argument("--preset", required=True, choices=preset_names())
    preset_apply.add_argument("--json", action="store_true")

    status = sub.add_parser("status")
    status.add_argument("--instance")
    status.add_argument("--agent")
    status.add_argument("--json", action="store_true")

    for name in ("create", "restore", "delete"):
        operation = sub.add_parser(name)
        operation.add_argument("--instance", required=True)
        operation.add_argument("--backup")
        operation.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    repository = repo()

    if args.command == "policy-list":
        output = repository.list_policies(agent_id=args.agent)
    elif args.command == "history":
        output = repository.history(args.policy_id)
    elif args.command == "jobs":
        output = repository.list_jobs(
            instance_id=args.instance,
            agent_id=args.agent,
            status=args.status,
        )
    elif args.command == "preset-list":
        output = [
            {"name": name, **PRESETS[name]}
            for name in preset_names()
        ]
    elif args.command == "preset-apply":
        output = repository.put_policy(
            apply_preset(args.instance, args.preset),
            requested_by=f"cli:preset:{args.preset}",
        )
    elif args.command == "status":
        output = repository.health(instance_id=args.instance, agent_id=args.agent)
    elif args.command == "policy-set":
        try:
            includes = json.loads(args.include_json)
            excludes = json.loads(args.exclude_json)
        except json.JSONDecodeError as exc:
            parser.error(str(exc))
        output = repository.put_policy(
            {
                "instance_id": args.instance,
                "enabled": args.enabled == "true",
                "mode": args.mode,
                "consistency": args.consistency,
                "compression": args.compression,
                "interval_seconds": args.interval,
                "retention_count": args.retention,
                "include_paths": includes,
                "exclude_paths": excludes,
            },
            requested_by="cli",
        )
    else:
        if args.command in {"restore", "delete"} and not args.backup:
            parser.error("--backup is required")
        output = repository.request(
            args.instance,
            action=args.command,
            backup_id=args.backup,
            reason="manual",
            requested_by="cli",
        )

    if getattr(args, "json", False):
        print(json.dumps(output, indent=2, sort_keys=True, default=str))
    elif args.command == "status":
        _print_health(output)
    elif args.command == "preset-list":
        for row in output:
            print(
                f"{row['name']:<12} interval={row['interval_seconds']:<7} "
                f"retention={row['retention_count']:<3} mode={row['mode']:<8} {row['description']}"
            )
    else:
        rows = output if isinstance(output, list) else [output.get("policy", output)]
        for row in rows:
            print(
                f"{row.get('instance_id', ''):<28} "
                f"{row.get('action', row.get('mode', '')):<10} "
                f"{row.get('status', '')} {row.get('backup_id', '') or ''}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
