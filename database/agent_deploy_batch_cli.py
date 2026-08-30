#!/usr/bin/env python3
"""Batch Agent deployment from a strict CSV contract."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import agent_deploy_cli

_REQUIRED = {"host", "ssh_user"}
_ALLOWED = {
    "host", "ssh_user", "platform", "ssh_port", "identity_file", "password_file",
    "controller_id", "controller_url", "region_id", "datacenter_id", "name",
    "port_range", "port_protocol", "release_tag", "package_file", "pairing_ttl",
    "connect_timeout", "bootstrap_timeout", "heartbeat_timeout",
}


def _integer(row: dict[str, str], name: str, default: int) -> int:
    raw = str(row.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _optional(row: dict[str, str], name: str) -> str | None:
    value = str(row.get(name) or "").strip()
    return value or None


def _row_args(row: dict[str, str]) -> SimpleNamespace:
    host = str(row.get("host") or "").strip()
    ssh_user = str(row.get("ssh_user") or "").strip()
    if not host:
        raise ValueError("host is required")
    if not ssh_user:
        raise ValueError("ssh_user is required")
    platform = str(row.get("platform") or "linux").strip().lower()
    if platform not in {"linux", "windows"}:
        raise ValueError("platform must be linux or windows")
    protocol = _optional(row, "port_protocol")
    if protocol and protocol not in {"tcp", "udp", "both"}:
        raise ValueError("port_protocol must be tcp, udp or both")
    return SimpleNamespace(
        host=host,
        platform=platform,
        ssh_user=ssh_user,
        ssh_port=_integer(row, "ssh_port", 22),
        identity_file=_optional(row, "identity_file"),
        password_file=_optional(row, "password_file"),
        controller_id=_optional(row, "controller_id"),
        controller_url=_optional(row, "controller_url"),
        region_id=_optional(row, "region_id"),
        datacenter_id=_optional(row, "datacenter_id"),
        name=_optional(row, "name"),
        port_range=_optional(row, "port_range"),
        port_protocol=protocol,
        release_tag=_optional(row, "release_tag"),
        package_file=_optional(row, "package_file"),
        pairing_ttl=_integer(row, "pairing_ttl", 900),
        connect_timeout=_integer(row, "connect_timeout", 10),
        bootstrap_timeout=_integer(row, "bootstrap_timeout", 900),
        heartbeat_timeout=_integer(row, "heartbeat_timeout", 180),
        json=True,
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ValueError(f"unable to read CSV: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle)
        fields = {str(item or "").strip() for item in (reader.fieldnames or [])}
        missing = sorted(_REQUIRED - fields)
        unknown = sorted(fields - _ALLOWED)
        if missing:
            raise ValueError("CSV missing required columns: " + ", ".join(missing))
        if unknown:
            raise ValueError("CSV contains unsupported columns: " + ", ".join(unknown))
        rows = [{str(key): str(value or "") for key, value in row.items()} for row in reader]
    if not rows:
        raise ValueError("CSV contains no Agent rows")
    return rows


def run_batch(path: Path, *, continue_on_error: bool = False) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for number, row in enumerate(_read_rows(path), start=2):
        host = str(row.get("host") or "").strip() or None
        try:
            payload = agent_deploy_cli.deploy(_row_args(row))
            results.append({"row": number, "host": host, "status": "completed", "deployment": payload})
        except Exception as exc:
            results.append({"row": number, "host": host, "status": "failed", "error": str(exc)})
            if not continue_on_error:
                break
    completed = sum(item["status"] == "completed" for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    return {
        "kind": "CapivaraAgentDeploymentBatch",
        "source": str(path),
        "completed": completed,
        "failed": failed,
        "processed": len(results),
        "ok": failed == 0,
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cap agent deploy-batch",
        description="Deploy multiple Agents from a CSV file using the normal secure deploy pipeline.",
    )
    parser.add_argument("csv_file")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_batch(Path(args.csv_file), continue_on_error=args.continue_on_error)
    except ValueError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Erro: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    else:
        print(f"Processados: {result['processed']} · concluídos: {result['completed']} · falhas: {result['failed']}")
        for item in result["results"]:
            suffix = item.get("error") or item.get("deployment", {}).get("agent_id") or ""
            print(f"linha {item['row']}: {item.get('host') or '-'} · {item['status']} · {suffix}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
