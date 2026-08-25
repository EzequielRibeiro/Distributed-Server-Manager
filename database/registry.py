#!/usr/bin/env python3
"""Capivara DSM ownership registry and bootstrap CLI."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from backend import DatabaseBackend, DatabaseConfig
from backend_factory import create_backend
from registry_demo_v2 import create_aurora_demo
from registry_repository import RegistryRepository
from runtime_backend import backend_from_environment
from user_repository import UserRepository
from users import hash_password

AURORA_LOGO = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'%3E"
    "%3Crect width='128' height='128' rx='24' fill='%230f172a'/%3E"
    "%3Cpath d='M64 18 103 93H25Z' fill='%2338bdf8'/%3E"
    "%3Ccircle cx='64' cy='72' r='17' fill='%23020617'/%3E%3C/svg%3E"
)


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return f"scrypt${2**14}$8$1${salt.hex()}${digest.hex()}"


def _repository(target: Path | DatabaseBackend) -> RegistryRepository:
    if isinstance(target, DatabaseBackend):
        return RegistryRepository(target)
    return RegistryRepository(
        create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(target).expanduser().resolve()),
            )
        )
    )


def _identity_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return slug or "local"


def installation_profile_identity(
    repository: RegistryRepository,
    *,
    profile: str,
    hostname: str,
    node_id: str | None = None,
    controller_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, object]:
    """Bootstrap deterministic local infrastructure identity for install.sh."""
    profile = str(profile).strip().lower()
    hostname = str(hostname).strip()
    if not hostname:
        raise ValueError("hostname is required")
    slug = _identity_slug(hostname)
    effective_node_id = str(node_id or hostname).strip()
    effective_controller_id = str(controller_id or f"controller-{slug}").strip()
    effective_agent_id = str(agent_id or f"agent-{slug}").strip()

    if profile == "controller":
        return repository.bootstrap_installation_profile(
            profile=profile,
            node_id=effective_node_id,
            node_name=hostname,
            controller_id=effective_controller_id,
            controller_name=f"Controller {hostname}",
        )
    if profile == "agent":
        return repository.bootstrap_installation_profile(
            profile=profile,
            node_id=effective_node_id,
            node_name=hostname,
            agent_id=effective_agent_id,
            agent_name=f"Agent {hostname}",
        )
    if profile == "hybrid":
        return repository.bootstrap_installation_profile(
            profile=profile,
            node_id=effective_node_id,
            node_name=hostname,
            controller_id=effective_controller_id,
            controller_name=f"Controller {hostname}",
            agent_id=effective_agent_id,
            agent_name=f"Agent {hostname}",
            region_id=f"region-local-{slug}",
            region_name="Local",
            datacenter_id=f"datacenter-local-{slug}",
            datacenter_name="Local Default",
        )
    raise ValueError(f"invalid installation profile: {profile}")


def create_aurora(
    root: Path,
    database_path: Path | DatabaseBackend,
) -> dict[str, object]:
    """Create the fictitious Aurora hierarchy using Baseline v2 identity."""
    instance_path = root / "instances" / "DemoNode" / "minecraft" / "cliente-demo"
    metadata_dir = instance_path / ".dsm"
    metadata_path = metadata_dir / "instance-metadata.json"
    repository = _repository(database_path)
    created = create_aurora_demo(
        repository,
        password_hash=password_hash("Aurora@2026!"),
        manifest_path=str(metadata_path),
        logo_url=AURORA_LOGO,
    )
    metadata = created["metadata"]
    metadata_dir.mkdir(parents=True, exist_ok=True)
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, metadata_path)
    return {
        "created": True,
        "controller_id": "controller-demo",
        "agent_id": "agent-demo",
        "customer_id": int(created["customer_id"]),
        "customer_code": str(created["customer_code"]),
        "instance_id": "cliente-demo",
        "instance": str(instance_path),
        "metadata": str(metadata_path),
    }


def purge_orphan_instance(
    root: Path,
    database_path: Path | DatabaseBackend,
    instance_id: str,
) -> dict[str, object]:
    """Remove a registry row only when no local instance directory exists."""
    if not instance_id or not all(
        part not in instance_id for part in ("/", "\\", "..")
    ):
        raise ValueError("invalid instance identifier")
    repository = _repository(database_path)
    row = repository.get_instance(instance_id)
    if row is None:
        raise ValueError("instance is not registered")
    instance_path = (
        root / "instances" / row["node_id"] / row["game_id"] / row["id"]
    )
    if instance_path.exists():
        raise ValueError(
            "instance has a local directory; use the instance administration danger zone instead"
        )
    runtime_path = (
        root / "runtime" / "resources" / row["node_id"] / row["game_id"] / row["id"]
    )
    repository.delete_instance(instance_id)
    if runtime_path.is_dir():
        import shutil

        shutil.rmtree(runtime_path)
    return {
        "purged": True,
        "instance_id": instance_id,
        "name": row["name"],
        "runtime_removed": not runtime_path.exists(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capivara DSM ownership registry")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("DSM_ROOT", "/opt/dsm")),
    )
    parser.add_argument("--database", type=Path)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("create-aurora", help="create the fictitious Aurora hierarchy")
    purge = subcommands.add_parser(
        "purge-orphan", help="remove an orphan instance record without a local directory"
    )
    purge.add_argument("instance_id")
    bootstrap = subcommands.add_parser(
        "bootstrap", help="create the first administrator, controller and agent"
    )
    bootstrap.add_argument("--admin", default="admin")
    bootstrap.add_argument("--admin-password-file", type=Path)
    bootstrap.add_argument("--controller-id", default="controller-main")
    bootstrap.add_argument("--controller-node-id", default="controller-node")
    bootstrap.add_argument("--controller-name", default="Controlador Principal")
    bootstrap.add_argument("--agent-id", default="agent-main")
    bootstrap.add_argument("--agent-node-id", default="agent-node")
    bootstrap.add_argument("--agent-name", default="Agente Principal")
    profile_bootstrap = subcommands.add_parser(
        "bootstrap-profile",
        help="bootstrap infrastructure identity for an installation profile",
    )
    profile_bootstrap.add_argument(
        "--profile", required=True, choices=("controller", "agent", "hybrid")
    )
    profile_bootstrap.add_argument("--hostname", required=True)
    profile_bootstrap.add_argument("--node-id")
    profile_bootstrap.add_argument("--controller-id")
    profile_bootstrap.add_argument("--agent-id")
    subcommands.add_parser("bootstrap-status", help="show initial topology status")
    args = parser.parse_args()
    root = args.root.resolve()
    target: Path | DatabaseBackend
    if args.database is not None or not os.environ.get("DSM_DATABASE_DRIVER"):
        target = (args.database or root / "data" / "capivara.db").resolve()
    else:
        target = backend_from_environment()

    if args.command == "create-aurora":
        payload = create_aurora(root, target)
    elif args.command == "purge-orphan":
        payload = purge_orphan_instance(root, target, args.instance_id)
    else:
        repository = _repository(target)
        if args.command == "bootstrap-status":
            payload = repository.topology_status()
        elif args.command == "bootstrap-profile":
            payload = installation_profile_identity(
                repository,
                profile=args.profile,
                hostname=args.hostname,
                node_id=args.node_id,
                controller_id=args.controller_id,
                agent_id=args.agent_id,
            )
        else:
            if args.admin_password_file:
                if not args.admin_password_file.is_file():
                    raise ValueError("administrator password file does not exist")
                if os.name != "nt" and args.admin_password_file.stat().st_mode & 0o077:
                    raise ValueError(
                        "administrator password file must use mode 600 or stricter"
                    )
                password = args.admin_password_file.read_text(
                    encoding="utf-8"
                ).rstrip("\r\n")
            else:
                password = getpass.getpass("Senha do administrador: ")
                confirmation = getpass.getpass("Confirme a senha: ")
                if password != confirmation:
                    raise ValueError("password confirmation does not match")
            payload = repository.bootstrap_topology(
                controller_id=args.controller_id,
                controller_node_id=args.controller_node_id,
                controller_name=args.controller_name,
                agent_id=args.agent_id,
                agent_node_id=args.agent_node_id,
                agent_name=args.agent_name,
            )
            users = UserRepository(repository.backend)
            existing = users.get(args.admin.lower())
            users.save(
                username=args.admin.lower(),
                password_hash=hash_password(password),
                role="admin",
                replace=existing is not None,
            )
            payload["administrator"] = args.admin.lower()
            payload["created"] = True
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
