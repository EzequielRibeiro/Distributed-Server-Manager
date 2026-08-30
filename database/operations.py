#!/usr/bin/env python3
"""Operational readiness diagnostics for Capivara DSM."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from controller_service_health import controller_service_health
from registry_repository import RegistryRepository
from runtime_backend import backend_from_environment
from user_repository import UserRepository


def _check(name: str, healthy: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "healthy": bool(healthy), "detail": detail}


def operational_readiness(root: Path) -> dict[str, Any]:
    """Return a secret-free operational readiness snapshot."""
    backend = backend_from_environment()
    registry = RegistryRepository(backend)
    users = UserRepository(backend)
    checks: list[dict[str, Any]] = []
    try:
        health = dict(backend.health_check())
        database_healthy = bool(
            health.get("valid", health.get("healthy", False))
        )
        checks.append(_check(
            "database", database_healthy,
            f"backend={backend.name}",
        ))
        topology = registry.topology_status()
        active_admins = sum(
            1 for user in users.list_users()
            if user["role"] == "admin" and bool(user["active"])
        )
        checks.extend((
            _check("administrator", active_admins > 0,
                   f"active_admins={active_admins}"),
            _check("controller", topology["controllers"] > 0,
                   f"controllers={topology['controllers']}"),
            _check("agent", topology["agents"] > 0,
                   f"agents={topology['agents']}"),
        ))
        service_health = controller_service_health()
        service_detail = "not checked"
        if service_health.get("checked"):
            inactive = list(service_health.get("inactive") or [])
            service_detail = "ready" if not inactive else "inactive=" + ",".join(inactive)
        checks.append(_check(
            "controller_services",
            bool(service_health.get("ready")),
            service_detail,
        ))
        required_directories = ("config", "data", "logs", "runtime")
        missing = [name for name in required_directories
                   if not (root / name).is_dir()]
        checks.append(_check(
            "filesystem", not missing,
            "ready" if not missing else "missing=" + ",".join(missing),
        ))
        password_file = os.environ.get("DSM_DATABASE_PASSWORD_FILE", "").strip()
        secret_healthy = True
        secret_detail = "not required"
        if password_file:
            path = Path(password_file)
            secret_healthy = path.is_file()
            secret_detail = "present" if secret_healthy else "missing"
            if secret_healthy and os.name != "nt" and path.stat().st_mode & 0o077:
                secret_healthy = False
                secret_detail = "permissions must be 600 or stricter"
        checks.append(_check("database_secret", secret_healthy, secret_detail))
        ready = all(item["healthy"] for item in checks)
        return {
            "schema_version": 1,
            "kind": "CapivaraOperationalReadiness",
            "ready": ready,
            "database_backend": backend.name,
            "topology": topology,
            "controller_services": service_health,
            "checks": checks,
        }
    finally:
        backend.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capivara DSM operational readiness diagnostics"
    )
    parser.add_argument(
        "--root", type=Path,
        default=Path(os.environ.get("DSM_ROOT", "/opt/dsm")),
    )
    parser.add_argument("command", choices=("readiness",))
    args = parser.parse_args(argv)
    payload = operational_readiness(args.root.resolve())
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
