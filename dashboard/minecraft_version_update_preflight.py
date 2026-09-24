#!/usr/bin/env python3
"""Customer-safe Minecraft runtime version-change preflight."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from content_repository import ContentRepository
from customer_instance_creation import _selector, runtime_definition
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from minecraft_content_resolver import MinecraftContentResolverError, resolve_minecraft_content
from minecraft_modpack_resolver import resolve_minecraft_modpack
from catalog_provisioning_resolver import resolve_catalog_provisioning


class MinecraftVersionUpdatePreflightService:
    def __init__(self, backend, root: Path):
        self.backend = backend
        self.root = Path(root)
        self.workspace = CustomerInstanceWorkspaceService(backend, self.root)
        self.content = ContentRepository(backend)

    def _context(self, user, instance_id: str) -> dict[str, Any]:
        context = self.workspace.require(user, instance_id, "instance.update")
        if str(context.get("game_id") or "").strip().lower() != "minecraft":
            raise PermissionError("Minecraft version update is available only for Minecraft instances")
        runtime_id = str(context.get("runtime_id") or "").strip()
        if not runtime_id:
            raise ValueError("instance runtime is unavailable")
        return context

    @staticmethod
    def _project_reference(item: dict[str, Any]) -> str | None:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        marker = metadata.get("minecraft_provider") if isinstance(metadata.get("minecraft_provider"), dict) else {}
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        provider_marker = provenance.get("minecraft_provider") if isinstance(provenance.get("minecraft_provider"), dict) else {}
        for source in (marker, provider_marker):
            value = str(source.get("project_id") or source.get("project_ref") or "").strip()
            if value:
                return value
        artifact = item.get("artifact") if isinstance(item.get("artifact"), dict) else {}
        package = str(artifact.get("package_id") or "").strip()
        if ":" in package:
            return package.split(":", 1)[0] or None
        return package or None

    @staticmethod
    def _modpack_reference(item: dict[str, Any]) -> str | None:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        marker = metadata.get("minecraft_modpack") if isinstance(metadata.get("minecraft_modpack"), dict) else {}
        value = str(marker.get("provider_project_id") or marker.get("project_id") or "").strip()
        if value:
            return value
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        marker = provenance.get("minecraft_modpack") if isinstance(provenance.get("minecraft_modpack"), dict) else {}
        value = str(marker.get("project_id") or "").strip()
        return value or None

    def _content_compatibility(self, instance_id: str, target_version: str, definition: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.content.list(instance_id=instance_id, limit=2000)
        result: list[dict[str, Any]] = []
        for item in rows:
            if str(item.get("desired_state") or "installed") != "installed":
                continue
            ctype = str(item.get("content_type") or "").strip().lower()
            provider = str(item.get("provider") or "").strip().lower()
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            bundle_marker = metadata.get("bundle") if isinstance(metadata.get("bundle"), dict) else {}
            parent_content_id = str(bundle_marker.get("parent_content_id") or "").strip()
            # Modpack children are owned by their parent bundle and cannot be
            # independently changed. Evaluate the modpack as one update unit.
            if parent_content_id and ctype != "modpack":
                continue
            activation = str(item.get("activation_state") or "enabled").strip().lower()
            base = {
                "content_id": str(item.get("content_id") or ""),
                "content_type": ctype,
                "provider": provider,
                "version": str(item.get("version") or ""),
                "activation_state": activation,
                "revision": int(item.get("revision") or 0),
                "can_disable": activation == "enabled" and ctype in {"mod", "plugin", "modpack", "datapack"},
                "can_remove": ctype in {"mod", "plugin", "modpack", "datapack"},
            }
            if activation == "disabled":
                result.append({**base, "compatibility": "disabled", "reason": "Conteúdo já está desativado."})
                continue
            try:
                if ctype == "modpack" and provider in {"modrinth", "curseforge"}:
                    project = self._modpack_reference(item)
                    if not project:
                        raise MinecraftContentResolverError("modpack project reference is unavailable")
                    resolve_minecraft_modpack(provider, project, str(item.get("content_id") or ""), target_version, definition)
                    result.append({**base, "compatibility": "compatible", "reason": "Existe modpack compatível para a versão alvo."})
                elif ctype in {"mod", "plugin"} and provider in {"modrinth", "curseforge"}:
                    project = self._project_reference(item)
                    if not project:
                        raise MinecraftContentResolverError("project reference is unavailable")
                    resolve_minecraft_content(provider, project, target_version, definition, ctype)
                    result.append({**base, "compatibility": "compatible", "reason": "Existe versão compatível no provider."})
                else:
                    result.append({**base, "compatibility": "unknown", "reason": "Compatibilidade não pode ser confirmada automaticamente para este conteúdo."})
            except MinecraftContentResolverError as exc:
                text = str(exc)
                incompatible = "no compatible" in text.lower() or "does not match" in text.lower()
                result.append({**base, "compatibility": "incompatible" if incompatible else "unknown", "reason": text[:500]})
            except Exception:
                result.append({**base, "compatibility": "unknown", "reason": "Não foi possível confirmar a compatibilidade no provider."})
        return result

    def preflight(self, user, instance_id: str, version: str, build: str) -> dict[str, Any]:
        context = self._context(user, instance_id)
        version = str(version or "").strip()
        build = str(build or "").strip()
        if not version or not build:
            raise ValueError("target version and build are required")
        runtime_id = str(context.get("runtime_id") or "").strip()
        definition = runtime_definition(self.root, "minecraft", runtime_id)
        selector = _selector(definition, version, build)
        selection, _configuration = resolve_catalog_provisioning(
            environment_id=runtime_id,
            selector=selector,
            selection={},
            configuration={},
            root=self.root,
        )
        resolved_version = str(selection.get("version") or version)
        resolved_build = str(selection.get("build") or build)
        content = self._content_compatibility(str(instance_id), resolved_version, definition)
        counts = {name: sum(1 for item in content if item["compatibility"] == name) for name in ("compatible", "incompatible", "unknown", "disabled")}
        blocking = counts["incompatible"] + counts["unknown"]
        return {
            "kind": "MinecraftVersionUpdatePreflight",
            "instance_id": str(instance_id),
            "runtime_id": runtime_id,
            "current": {
                "version": str(context.get("game_version") or ""),
                "build": str(context.get("build_id") or ""),
            },
            "target": {
                "version": resolved_version,
                "build": resolved_build,
                "selector": selector,
            },
            "content": content,
            "summary": counts,
            "requires_confirmation": True,
            "has_known_incompatibilities": counts["incompatible"] > 0,
            "has_unverified_content": counts["unknown"] > 0,
            "has_blocking_content": blocking > 0,
            "blocking_content_count": blocking,
            "can_request_update": blocking == 0,
            "warning": "A troca de versão só é liberada quando todo conteúdo ativo possui compatibilidade confirmada. Conteúdo incompatível ou não verificável deve ser removido, atualizado ou desativado antes da operação.",
        }


__all__ = ["MinecraftVersionUpdatePreflightService"]
