#!/usr/bin/env python3
"""Customer-triggered transactional Minecraft runtime migrations."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from catalog_provisioning_resolver import resolve_catalog_provisioning
from customer_instance_creation import _selector, runtime_definition
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from minecraft_version_update_preflight import MinecraftVersionUpdatePreflightService
from runtime_workspace_catalog import allowed_runtimes


class MinecraftRuntimeMigrationService:
    def __init__(self, backend, root: Path):
        self.backend = backend
        self.root = Path(root)
        self.workspace = CustomerInstanceWorkspaceService(backend, self.root)
        self.compatibility = MinecraftVersionUpdatePreflightService(backend, self.root)

    @staticmethod
    def _isolated_install_dir(instance_id: str, runtime_id: str, version: str, build: str) -> str:
        identity = hashlib.sha256(str(instance_id).encode("utf-8")).hexdigest()[:20]
        release = hashlib.sha256(f"{runtime_id}\0{version}\0{build}".encode("utf-8")).hexdigest()[:12]
        return f"instance-{identity}-{release}"

    def _context(self, user: dict[str, Any], instance_id: str) -> dict[str, Any]:
        context = self.workspace.require(user, instance_id, "instance.update")
        if str(context.get("game_id") or "").strip().lower() != "minecraft":
            raise PermissionError("Minecraft runtime migration is available only for Minecraft instances")
        return context

    def _target_definition(self, context: dict[str, Any], target_runtime_id: str) -> dict[str, Any]:
        target_runtime_id = str(target_runtime_id or "").strip()
        if not target_runtime_id:
            raise ValueError("target runtime is required")
        permitted = {
            str(item.get("runtime_id") or "")
            for item in allowed_runtimes(
                self.root,
                "minecraft",
                context.get("contract_metadata") or {},
            )
        }
        if target_runtime_id not in permitted:
            raise PermissionError("target runtime is not allowed by this contract")
        current_runtime_id = str(context.get("runtime_id") or "").strip()
        if target_runtime_id == current_runtime_id:
            raise ValueError("target runtime is already active")
        current = runtime_definition(self.root, "minecraft", current_runtime_id)
        target = runtime_definition(self.root, "minecraft", target_runtime_id)
        if not current or not target:
            raise ValueError("runtime definition is unavailable")
        current_edition = str(current.get("edition") or "").strip().lower()
        target_edition = str(target.get("edition") or "").strip().lower()
        if current_edition != target_edition:
            raise ValueError("runtime migration across Minecraft editions is not supported")
        if target_edition != "java":
            raise ValueError("runtime migration is currently supported only within Minecraft Java")
        return target

    def preflight(
        self,
        user: dict[str, Any],
        instance_id: str,
        target_runtime_id: str,
        version: str,
        build: str,
    ) -> dict[str, Any]:
        context = self._context(user, instance_id)
        target = self._target_definition(context, target_runtime_id)
        version = str(version or "").strip()
        build = str(build or "").strip()
        if not version or not build:
            raise ValueError("target version and build are required")
        selector = _selector(target, version, build)
        selection, _configuration = resolve_catalog_provisioning(
            environment_id=str(target_runtime_id),
            selector=selector,
            selection={},
            configuration={},
            root=self.root,
        )
        resolved_version = str(selection.get("version") or version)
        resolved_build = str(selection.get("build") or build)
        content = self.compatibility._content_compatibility(
            str(instance_id),
            resolved_version,
            target,
        )
        counts = {
            name: sum(1 for item in content if item["compatibility"] == name)
            for name in ("compatible", "incompatible", "unknown", "disabled")
        }
        blocking = counts["incompatible"] + counts["unknown"]
        return {
            "kind": "MinecraftRuntimeMigrationPreflight",
            "instance_id": str(instance_id),
            "current": {
                "runtime_id": str(context.get("runtime_id") or ""),
                "version": str(context.get("game_version") or ""),
                "build": str(context.get("build_id") or ""),
            },
            "target": {
                "runtime_id": str(target_runtime_id),
                "version": resolved_version,
                "build": resolved_build,
                "selector": selector,
                "label": str(target.get("name") or target_runtime_id),
                "edition": str(target.get("edition") or ""),
            },
            "content": content,
            "summary": counts,
            "has_blocking_content": blocking > 0,
            "blocking_content_count": blocking,
            "can_request_migration": blocking == 0,
            "warning": (
                "A migração mantém a mesma instância, mundo, portas, plano e permissões. "
                "O runtime atual só será substituído após backup, materialização isolada e readiness do runtime alvo."
            ),
        }

    def request(
        self,
        user: dict[str, Any],
        instance_id: str,
        target_runtime_id: str,
        version: str,
        build: str,
        *,
        confirm_risk: bool,
    ) -> dict[str, Any]:
        if confirm_risk is not True:
            raise ValueError("explicit runtime-migration confirmation is required")
        preflight = self.preflight(user, instance_id, target_runtime_id, version, build)
        if not preflight.get("can_request_migration"):
            raise ValueError("incompatible or unverified managed content must be removed, updated or disabled before changing Minecraft runtime")

        context = self._context(user, instance_id)
        target = preflight["target"]
        target_runtime_id = str(target["runtime_id"])
        target_definition = runtime_definition(self.root, "minecraft", target_runtime_id)
        target_version = str(target["version"])
        target_build = str(target["build"])
        selector = str(target["selector"])
        selection, configuration = resolve_catalog_provisioning(
            environment_id=target_runtime_id,
            selector=selector,
            selection={},
            configuration={},
            root=self.root,
        )
        selection = dict(selection)
        selection["install_dir"] = self._isolated_install_dir(
            str(instance_id), target_runtime_id, target_version, target_build
        )

        runtime = self.workspace._runtime_projection(context)
        desired_state = "running" if str(runtime.get("state") or "").lower() in {"running", "starting"} else "stopped"
        configuration = dict(configuration or {})
        configuration["minecraft_runtime_migration"] = {
            "kind": "MinecraftRuntimeMigration",
            "from_runtime_id": str(context.get("runtime_id") or ""),
            "from_version": str(context.get("game_version") or ""),
            "from_build": str(context.get("build_id") or ""),
            "target_runtime_id": target_runtime_id,
            "target_version": target_version,
            "target_build": target_build,
            "edition": str(target_definition.get("edition") or ""),
            "isolated_install_dir": selection["install_dir"],
            "backup_before_update": True,
            "confirmed_risk": True,
        }

        jobs = AgentInstanceProvisioningRepository(self.backend)
        jobs.initialize()
        state = jobs.enqueue(
            agent_id=str(context.get("agent_id") or ""),
            instance_id=str(instance_id),
            environment_id=target_runtime_id,
            selector=selector,
            selection=selection,
            configuration=configuration,
            desired_state=desired_state,
            requested_by=str(user.get("username") or user.get("id") or "customer"),
        )
        return {
            "accepted": True,
            "instance_id": str(instance_id),
            "provisioning_id": state["provisioning_id"],
            "status": state["status"],
            "desired_state": desired_state,
            "target": target,
            "warning": preflight.get("warning"),
        }


__all__ = ["MinecraftRuntimeMigrationService"]
