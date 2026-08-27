#!/usr/bin/env python3
"""Capivara DSM ownership registry and bootstrap CLI."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
from pathlib import Path

from backend import DatabaseBackend, DatabaseConfig
from backend_factory import create_backend
from registry_repository import RegistryRepository
from runtime_backend import backend_from_environment
from user_repository import UserRepository
from users import hash_password


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


def create_aurora(root: Path, database_path: Path | DatabaseBackend) -> dict[str, object]:
    """Compatibility hook used only by the isolated registry test suite."""
    from tests.fixtures.registry_demo import create_registry_fixture

    adapter = type("RegistryFixtureAdapter", (), {"_repository": staticmethod(_repository)})
    return create_registry_fixture(root, adapter, database_path)


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
    repository.delete_instance(instance_id)
    return {
        "purged": True,
        "instance_id": instance_id,
        "name": row["name"],
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

    if args.command == "purge-orphan":
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
