#!/usr/bin/env python3
"""Canonical Catalog v2 customer instance creation integration.

The legacy dashboard still contains the pre-migration runtime path
``catalog/v2/runtimes/<game>``. Current Catalog v2 stores RuntimeDefinitions
under ``catalog/v2/games/<game>/runtimes``. This module keeps the customer
creation flow on the canonical layout without reintroducing a second catalog.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any


def runtime_directory(root: Path, game: str) -> Path:
    """Return the canonical RuntimeDefinition directory for ``game``."""
    return Path(root) / "catalog" / "v2" / "games" / game / "runtimes"


def runtime_definition(root: Path, game: str, runtime_id: str) -> dict[str, Any]:
    """Resolve one RuntimeDefinition from the canonical Catalog v2 layout."""
    definitions = runtime_directory(root, game)
    if not definitions.is_dir():
        raise ValueError("game is not available in the catalog")

    for path in definitions.glob("*.json"):
        try:
            definition = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if definition.get("id") == runtime_id:
            return definition

    raise ValueError("runtime definition not found")


def install_customer_instance_creation(legacy) -> None:
    """Install the canonical customer creation flow into the legacy module."""

    def create_customer_instance(
        user,
        payload,
        root=None,
        database_path=None,
    ):
        root = Path(root or legacy.DSM_ROOT)
        database_path = database_path or legacy.DATABASE_FILE

        if not user or user.get("role") != "customer" or not user.get("scope_id"):
            raise PermissionError("only a scoped customer can create an instance")

        game = str(payload.get("game", "")).strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", game):
            raise ValueError("invalid game")

        runtime_id = str(payload.get("runtime_id", "")).strip()
        edition = str(payload.get("edition", "")).strip()
        version = str(payload.get("version", "")).strip()
        build = str(payload.get("build", "")).strip()
        for value, label in (
            (runtime_id, "runtime_id"),
            (edition, "edition"),
            (version, "version"),
            (build, "build"),
        ):
            if not value:
                raise ValueError(f"{label} is required")

        if not re.fullmatch(r"[A-Za-z0-9._-]+", runtime_id):
            raise ValueError("invalid runtime_id")

        if not runtime_directory(root, game).is_dir():
            raise ValueError("game is not available in the catalog")

        try:
            runtime_def = runtime_definition(root, game, runtime_id)
        except ValueError as exc:
            raise ValueError(
                "requested runtime_id is not available for this game"
            ) from exc

        variant = (
            runtime_def.get("variant")
            or runtime_def.get("loader")
            or runtime_def.get("edition")
        )
        repository = legacy.dashboard_repository(database_path)
        placement = legacy.resolve_instance_placement(user, payload, repository)
        contract_id = str(payload.get("contract_id", "")).strip() or None

        def occupied_ports_provider(
            agent_id: str,
            node_id: str,
            protocol: str,
            start_port: int,
            end_port: int,
        ) -> set[int]:
            return legacy.occupied_ports_for_agent(
                agent_id,
                node_id,
                protocol,
                start_port,
                end_port,
                backend=repository.backend,
            )

        plan = repository.create_customer_instance(
            customer_id=user["scope_id"],
            username=user["username"],
            game=game,
            runtime_id=runtime_id,
            edition=edition,
            variant=variant,
            version=version,
            build=build,
            instances_root=root / "instances",
            contract_id=contract_id,
            selected_agent_id=placement["agent_id"],
            network_profile=runtime_def.get("network"),
            occupied_ports_provider=occupied_ports_provider,
            resource_profile_id=(
                str(payload.get("resource_profile_id") or "").strip() or None
            ),
        )

        instance_path = plan["instance_path"]
        metadata_path = plan["metadata_path"]
        metadata = plan["metadata"]
        try:
            metadata_path.parent.mkdir(parents=True, exist_ok=False)
            (instance_path / "config").mkdir()
            (instance_path / "config" / "server.conf").write_text(
                f'# Configuração da instância {plan["name"]}\n'
                f'INSTANCE_ID="{plan["instance_id"]}"\nGAME_ID="{game}"\n',
                encoding="utf-8",
            )
            metadata_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            resource = (
                root
                / "runtime"
                / "resources"
                / plan["node_id"]
                / game
                / plan["instance_id"]
            )
            resource.mkdir(parents=True, exist_ok=False)
            (resource / "instance.json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (resource / "server.json").write_text(
                json.dumps(
                    {"status": {"state": "provisioning", "health": "pending"}},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception:
            repository.delete_instance(plan["instance_id"])
            if instance_path.exists():
                shutil.rmtree(instance_path)
            raise

        provision = legacy.start_instance_provisioning(
            root,
            database_path,
            plan["instance_id"],
            plan["node_id"],
            game,
            runtime_id,
            edition,
            version,
            build,
            instance_path,
            plan["agent_id"],
        )
        return {
            "created": True,
            "instance_id": plan["instance_id"],
            "name": plan["name"],
            "instance": str(instance_path),
            "agent_id": plan["agent_id"],
            "node_id": plan["node_id"],
            "game": game,
            "contract_id": plan["contract_id"],
            "placement": {
                "region_id": placement.get("region_id"),
                "datacenter_id": placement.get("datacenter_id"),
                "score": placement.get("score"),
                "reason": placement.get("reason"),
            },
            "provision": provision,
        }

    legacy._runtime_definition = runtime_definition
    legacy.create_customer_instance = create_customer_instance


__all__ = [
    "install_customer_instance_creation",
    "runtime_definition",
    "runtime_directory",
]
