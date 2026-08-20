#!/usr/bin/env python3
"""Stable public contract for Capivara infrastructure diagnostics."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from infrastructure_doctor import InfrastructureDoctor
from runtime_backend import backend_from_environment

SCHEMA_VERSION = 1
KIND = "CapivaraInfrastructureDoctor"
SCOPE = "infrastructure"
VALID_STATUSES = {"healthy", "degraded", "critical"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _global_status(payload: dict[str, Any]) -> str:
    findings = list(payload.get("findings") or [])
    severities = {
        str(item.get("severity") or "").strip().lower()
        for item in findings
        if isinstance(item, dict)
    }
    if "critical" in severities or not bool(payload.get("ready")):
        return "critical"
    if "warning" in severities:
        return "degraded"
    return "healthy"


def build_infrastructure_doctor_payload(
    backend,
    *,
    reconcile: bool = False,
) -> dict[str, Any]:
    """Return the canonical, versioned Doctor payload.

    Normal execution remains observational because the underlying engine is
    invoked with ``reconcile=False`` unless the caller explicitly requests the
    mutation boundary.
    """
    raw = InfrastructureDoctor(backend).diagnose(reconcile=reconcile)
    payload = {
        **raw,
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "scope": SCOPE,
        "generated_at": _timestamp(),
    }
    payload["status"] = _global_status(payload)
    return payload


def _print_human(payload: dict[str, Any]) -> None:
    print(
        f"Doctor: {payload['status']} | scope={payload['scope']} | "
        f"generated_at={payload['generated_at']}"
    )
    for item in payload.get("summary") or []:
        print(
            f"{str(item.get('label', '')):<20} "
            f"{str(item.get('status', '')):<10} "
            f"{str(item.get('detail', ''))}"
        )
    repairs = list(payload.get("repairs") or [])
    if repairs:
        print("\nReconciliação segura:")
        for action in repairs:
            print(
                f"- {action.get('agent_id')}: health "
                f"{action.get('from')} -> {action.get('to')}"
            )
    findings = list(payload.get("findings") or [])
    if findings:
        print("\nAchados:")
        for finding in findings:
            subject = (
                f" [{finding.get('subject_id')}]"
                if finding.get("subject_id")
                else ""
            )
            print(
                f"- {str(finding.get('severity', '')).upper()} "
                f"{finding.get('code')}{subject}: {finding.get('message')}"
            )
            if finding.get("recommendation"):
                print(f"  Ação: {finding['recommendation']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capivara infrastructure doctor")
    parser.add_argument("command", nargs="?", default="doctor", choices=("doctor",))
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="aplica somente reconciliações determinísticas e seguras",
    )
    parser.add_argument("--json", action="store_true", help="saída estruturada")
    args = parser.parse_args(argv)

    backend = backend_from_environment()
    try:
        payload = build_infrastructure_doctor_payload(
            backend,
            reconcile=args.reconcile,
        )
    finally:
        backend.close()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_human(payload)
    return 0 if payload["ready"] else 1


__all__ = [
    "KIND",
    "SCHEMA_VERSION",
    "SCOPE",
    "VALID_STATUSES",
    "build_infrastructure_doctor_payload",
]


if __name__ == "__main__":
    raise SystemExit(main())
