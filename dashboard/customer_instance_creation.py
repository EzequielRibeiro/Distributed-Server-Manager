#!/usr/bin/env python3
"""Canonical Catalog v2 customer instance creation integration.

Customer instance records live on the Controller, but runtime provisioning is
owned by the selected Agent.  This integration keeps the small Controller-side
metadata/read-model shadow required by the current Dashboard while routing all
content installation and runtime materialization through the persistent B10
Controller -> Agent provisioning pipeline.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from catalog_provisioning_resolver import resolve_catalog_provisioning
from instance_network import occupied_ports_provider_for_backend
from instance_provisioning_projection import (
    dashboard_provision_state,
    project_agent_provisioning,
)


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


def _selector(runtime_def: dict[str, Any], version: str, build: str) -> str:
    resolver = str((runtime_def.get("version") or {}).get("resolver") or "").strip().lower()
    if resolver == "papermc" and build:
        return f"{version}@{build}"
    return version or str(runtime_def.get("variant") or runtime_def.get("edition") or "current")


def _queue_agent_provisioning(
    *,
    root: Path,
    repository,
    runtime_def: dict[str, Any],
    instance_id: str,
    agent_id: str,
    runtime_id: str,
    version: str,
    build: str,
    requested_by: str,
    resource_profile_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selector = _selector(runtime_def, version, build)
    requested_configuration: dict[str, Any] = {}
    if resource_profile_id:
        requested_configuration["resource_profile_id"] = resource_profile_id
    selection, configuration = resolve_catalog_provisioning(
        environment_id=runtime_id,
        selector=selector,
        selection={},
        configuration=requested_configuration,
        root=root,
    )
    jobs = AgentInstanceProvisioningRepository(repository.backend)
    jobs.initialize()
    state = jobs.enqueue(
        agent_id=agent_id,
        instance_id=instance_id,
        environment_id=runtime_id,
        selector=selector,
        selection=selection,
        configuration=configuration,
        desired_state="stopped",
        requested_by=requested_by,
    )
    try:
        provision = project_agent_provisioning(repository.backend, state, root=root)
    except Exception:
        # The B10 queue is authoritative.  A read-model projection failure must
        # never cause a queued Agent operation to be orphaned or duplicated.
        provision = dashboard_provision_state(state)
    return state, provision


def install_customer_instance_creation(legacy) -> None:
    """Install canonical, Agent-owned customer provisioning into legacy routes."""

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
        occupied_ports_provider = occupied_ports_provider_for_backend(repository.backend)
        resource_profile_id = str(payload.get("resource_profile_id") or "").strip() or None

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
            resource_profile_id=resource_profile_id,
        )

        instance_path = plan["instance_path"]
        metadata_path = plan["metadata_path"]
        metadata = plan["metadata"]
        resource = (
            root
            / "runtime"
            / "resources"
            / plan["node_id"]
            / game
            / plan["instance_id"]
        )
        try:
            # Control-plane shadow only.  No game-data or runtime files are
            # copied/materialized on the Controller for an Agent-owned instance.
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
            resource.mkdir(parents=True, exist_ok=False)
            (resource / "instance.json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (resource / "server.json").write_text(
                json.dumps(
                    {"status": {"state": "queued", "health": "pending"}},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            _, provision = _queue_agent_provisioning(
                root=root,
                repository=repository,
                runtime_def=runtime_def,
                instance_id=plan["instance_id"],
                agent_id=plan["agent_id"],
                runtime_id=runtime_id,
                version=version,
                build=build,
                requested_by=str(user.get("username") or "customer"),
                resource_profile_id=resource_profile_id,
            )
        except Exception:
            repository.delete_instance(plan["instance_id"])
            if instance_path.exists():
                shutil.rmtree(instance_path)
            if resource.exists():
                shutil.rmtree(resource)
            raise

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

    def retry_instance_provisioning(
        user,
        instance_path,
        database_path=None,
    ):
        database_path = database_path or legacy.DATABASE_FILE
        instance = Path(legacy.catalog_instance_path(str(instance_path)))
        relative = instance.relative_to(legacy.INSTANCE_ROOT)
        if len(relative.parts) != 3:
            raise ValueError("instance path must identify server, game and instance")
        node_id, game, instance_id = relative.parts
        repository = legacy.dashboard_repository(database_path)
        row = repository.reserve_retry(instance_id, node_id, game)
        runtime_id = str(row["runtime_id"] or "").strip()
        edition = str(row["edition"] or "").strip()
        version = str(row["game_version"] or "").strip()
        build = str(row["build_id"] or "").strip()
        agent_id = str(row["agent_id"] or "").strip()
        if not all((runtime_id, edition, version, build, agent_id)):
            repository.update_instance_status(instance_id, row["status"])
            raise ValueError("instance runtime selection is incomplete")
        runtime_def = runtime_definition(Path(legacy.DSM_ROOT), game, runtime_id)
        try:
            _, provision = _queue_agent_provisioning(
                root=Path(legacy.DSM_ROOT),
                repository=repository,
                runtime_def=runtime_def,
                instance_id=instance_id,
                agent_id=agent_id,
                runtime_id=runtime_id,
                version=version,
                build=build,
                requested_by=str((user or {}).get("username") or "customer"),
            )
        except Exception:
            repository.update_instance_status(instance_id, row["status"])
            raise
        legacy.audit(
            user,
            "instance.provision.retry",
            "started",
            instance_id,
            f"runtime={runtime_id};version={version};build={build};transport=agent-b10",
            database_path=database_path,
        )
        return {
            "retried": True,
            "instance_id": instance_id,
            "runtime_id": runtime_id,
            "edition": edition,
            "version": version,
            "build": build,
            "provision": provision,
        }

    # Compatibility symbols consumed by the still-composed legacy HTTP layer.
    legacy._runtime_definition = runtime_definition
    legacy.create_customer_instance = create_customer_instance
    legacy.retry_instance_provisioning = retry_instance_provisioning


__all__ = [
    "install_customer_instance_creation",
    "runtime_definition",
    "runtime_directory",
]
