#!/usr/bin/env python3
"""Customer-triggered transactional Minecraft runtime version changes."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from catalog_provisioning_resolver import resolve_catalog_provisioning
from customer_instance_creation import _selector, runtime_definition
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from minecraft_version_update_preflight import MinecraftVersionUpdatePreflightService


class MinecraftVersionUpdateService:
    def __init__(self, backend, root: Path):
        self.backend = backend
        self.root = Path(root)
        self.workspace = CustomerInstanceWorkspaceService(backend, self.root)
        self.preflight_service = MinecraftVersionUpdatePreflightService(backend, self.root)

    @staticmethod
    def _isolated_install_dir(instance_id: str, runtime_id: str, version: str, build: str) -> str:
        identity = hashlib.sha256(str(instance_id).encode("utf-8")).hexdigest()[:20]
        release = hashlib.sha256(f"{runtime_id}\0{version}\0{build}".encode("utf-8")).hexdigest()[:12]
        return f"instance-{identity}-{release}"

    def request(
        self,
        user: dict[str, Any],
        instance_id: str,
        version: str,
        build: str,
        *,
        confirm_risk: bool,
    ) -> dict[str, Any]:
        if confirm_risk is not True:
            raise ValueError("explicit compatibility-risk confirmation is required")

        preflight = self.preflight_service.preflight(user, instance_id, version, build)
        if not preflight.get("can_request_update"):
            raise ValueError("incompatible or unverified managed content must be removed, updated or disabled before changing Minecraft version")

        context = self.workspace.require(user, instance_id, "instance.update")
        runtime_id = str(context.get("runtime_id") or "").strip()
        definition = runtime_definition(self.root, "minecraft", runtime_id)
        target = preflight.get("target") if isinstance(preflight.get("target"), dict) else {}
        target_version = str(target.get("version") or version).strip()
        target_build = str(target.get("build") or build).strip()
        selector = _selector(definition, target_version, target_build)

        selection, configuration = resolve_catalog_provisioning(
            environment_id=runtime_id,
            selector=selector,
            selection={},
            configuration={},
            root=self.root,
        )
        selection = dict(selection)
        selection["install_dir"] = self._isolated_install_dir(
            str(instance_id), runtime_id, target_version, target_build
        )

        runtime = self.workspace._runtime_projection(context)
        desired_state = "running" if str(runtime.get("state") or "").lower() in {"running", "starting"} else "stopped"
        update_meta = {
            "kind": "MinecraftVersionUpdate",
            "from_version": str(context.get("game_version") or ""),
            "from_build": str(context.get("build_id") or ""),
            "target_version": target_version,
            "target_build": target_build,
            "runtime_id": runtime_id,
            "isolated_install_dir": selection["install_dir"],
            "backup_before_update": True,
            "confirmed_risk": True,
        }
        configuration = dict(configuration or {})
        configuration["minecraft_version_update"] = update_meta

        jobs = AgentInstanceProvisioningRepository(self.backend)
        jobs.initialize()
        state = jobs.enqueue(
            agent_id=str(context.get("agent_id") or ""),
            instance_id=str(instance_id),
            environment_id=runtime_id,
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
            "target": {
                "version": target_version,
                "build": target_build,
                "selector": selector,
            },
            "preflight": {
                "summary": preflight.get("summary") or {},
                "unknown_content_count": int((preflight.get("summary") or {}).get("unknown") or 0),
            },
            "warning": preflight.get("warning"),
        }


__all__ = ["MinecraftVersionUpdateService"]
