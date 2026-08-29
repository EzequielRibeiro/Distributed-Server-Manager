#!/usr/bin/env python3
"""Non-destructive OpenSSH preflight for one or many prospective Agents."""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "core", ROOT / "database"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from agent_batch_targets import load_csv_targets, normalize_concurrency, target_from_values
from agent_ssh_deploy import AgentDeployError, SSHDeployOptions, preflight_ssh, preflight_windows_ssh


def build_parser():
    p = argparse.ArgumentParser(
        description="Test SSH access to one or many Linux/Windows hosts without installing an Agent",
        epilog=(
            "Passwords are never accepted directly on the command line or in CSV. "
            "Use --password-file for a protected 0600 file, or --identity-file for an SSH private key."
        ),
    )
    p.add_argument("host", nargs="?", help="single remote host")
    p.add_argument("--hosts-file", help="CSV containing batch targets")
    p.add_argument("--platform", choices=("linux", "windows"), default="linux")
    p.add_argument("--ssh-user")
    p.add_argument("--ssh-port", type=int, default=22)
    auth = p.add_mutually_exclusive_group()
    auth.add_argument("--identity-file", help="SSH private key")
    auth.add_argument("--password-file", help="protected 0600 password file; requires sshpass")
    p.add_argument("--connect-timeout", type=int, default=10)
    p.add_argument("--concurrency", type=int, default=5, help="batch workers, 1-20; default: 5")
    p.add_argument("--json", action="store_true")
    return p


def _targets(args):
    if bool(args.host) == bool(args.hosts_file):
        raise ValueError("use exactly one HOST or --hosts-file CSV")
    defaults = {
        "ssh_user": args.ssh_user,
        "ssh_port": args.ssh_port,
        "platform": args.platform,
        "password_file": args.password_file,
        "identity_file": args.identity_file,
    }
    if args.hosts_file:
        return load_csv_targets(args.hosts_file, defaults=defaults), True
    return [target_from_values(host=args.host, **defaults)], False


def _test(target, connect_timeout):
    options = SSHDeployOptions(
        host=target.host,
        ssh_user=target.ssh_user,
        ssh_port=target.ssh_port,
        identity_file=target.identity_file,
        password_file=target.password_file,
        connect_timeout=connect_timeout,
    )
    try:
        result = (preflight_windows_ssh if target.platform == "windows" else preflight_ssh)(options)
        return {
            "ok": True,
            "host": target.host,
            "name": target.name,
            "ssh_user": target.ssh_user,
            "ssh_port": target.ssh_port,
            "platform": result.get("platform", target.platform),
            "architecture": result.get("architecture"),
            "transport": "openssh",
            "authentication": "password-file" if target.password_file else ("identity-file" if target.identity_file else "ssh-agent/default-key"),
            "privilege": result.get("privilege"),
            "status": "reachable",
        }
    except AgentDeployError as exc:
        return {
            "ok": False,
            "host": target.host,
            "name": target.name,
            "ssh_user": target.ssh_user,
            "ssh_port": target.ssh_port,
            "platform": target.platform,
            "transport": "openssh",
            "authentication": "password-file" if target.password_file else ("identity-file" if target.identity_file else "ssh-agent/default-key"),
            "status": "failed",
            "error": str(exc),
        }


def _run_batch(targets, *, connect_timeout, concurrency):
    workers = min(normalize_concurrency(concurrency), len(targets))
    results = [None] * len(targets)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cap-ssh-test") as executor:
        futures = {executor.submit(_test, target, connect_timeout): index for index, target in enumerate(targets)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    succeeded = sum(1 for item in results if item and item["ok"])
    return {
        "ok": succeeded == len(results),
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "targets": results,
    }


def _print_single(out):
    if not out["ok"]:
        print(f"Erro: {out['error']}", file=sys.stderr)
        return
    print("Capivara Agent Connection Test\n")
    print(f"Host.............. {out['host']}:{out['ssh_port']}")
    print("SSH............... OK")
    print(f"Platform.......... {out.get('platform')}")
    print(f"Architecture...... {out.get('architecture')}")
    print(f"Authentication.... {out.get('authentication')}")
    print(f"Privilege......... {out.get('privilege') or 'administrator'}")
    print("Ready............. YES")


def _print_batch(out):
    print("Capivara Agent Batch Connection Test\n")
    for item in out["targets"]:
        label = item.get("name") or item["host"]
        state = "OK" if item["ok"] else "FALHOU"
        detail = f"{item.get('platform','?')} {item.get('architecture') or ''}".strip() if item["ok"] else item.get("error", "unknown error")
        print(f"{label:<24} {item['host']}:{item['ssh_port']:<5} {state:<7} {detail}")
    print(f"\nTotal: {out['total']} · OK: {out['succeeded']} · Falhas: {out['failed']}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        targets, batch = _targets(args)
        if not 1 <= int(args.connect_timeout) <= 300:
            raise ValueError("--connect-timeout must be between 1 and 300")
        if batch:
            payload = _run_batch(targets, connect_timeout=args.connect_timeout, concurrency=args.concurrency)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            else:
                _print_batch(payload)
            return 0 if payload["ok"] else 3
        payload = _test(targets[0], args.connect_timeout)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            _print_single(payload)
        return 0 if payload["ok"] else 2
    except (ValueError, OSError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        parser.exit(2, f"Erro: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
