"""Bind re-attested Server Pack evidence to the exact NeoForge selection.

This adapter is preparation-only. It validates the Controller-resolved runtime
selection and stages the already quarantined Server Pack. It does not install
NeoForge, mutate an instance, start/stop a server, or publish Controller state.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from minecraft_serverpack_migration_staging import stage_serverpack_archive

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MinecraftServerPackMigrationAdapterError(RuntimeError):
    pass


def prepare_migration_inputs(
    *,
    archive: Path,
    stage_root: Path,
    migration: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(migration, Mapping) or not isinstance(selection, Mapping):
        raise MinecraftServerPackMigrationAdapterError(
            "migration and runtime selection are required"
        )
    runtime_id = str(selection.get("runtime_definition") or "").strip()
    game = str(selection.get("game") or "").strip().lower()
    version = str(selection.get("version") or "").strip()
    build = str(selection.get("build") or selection.get("tag") or "").strip()
    install_dir = str(selection.get("install_dir") or "").strip()
    if runtime_id != "minecraft.java.neoforge" or game != "minecraft":
        raise MinecraftServerPackMigrationAdapterError(
            "migration requires a Minecraft Java NeoForge runtime selection"
        )
    if version != str(migration.get("minecraft_version") or "").strip():
        raise MinecraftServerPackMigrationAdapterError(
            "runtime selection Minecraft version differs from migration evidence"
        )
    if build != str(migration.get("target_loader_version") or "").strip():
        raise MinecraftServerPackMigrationAdapterError(
            "runtime selection NeoForge build differs from migration evidence"
        )
    if install_dir != str(migration.get("isolated_install_dir") or "").strip():
        raise MinecraftServerPackMigrationAdapterError(
            "runtime selection is not bound to the isolated install directory"
        )
    if str(selection.get("provider") or "").strip().lower() != "http":
        raise MinecraftServerPackMigrationAdapterError(
            "NeoForge migration requires the catalog HTTP artifact"
        )
    installer = selection.get("installer")
    if not isinstance(installer, Mapping) or str(installer.get("type") or "") != "java_jar":
        raise MinecraftServerPackMigrationAdapterError(
            "NeoForge migration requires the catalog Java installer"
        )
    asset = selection.get("asset")
    if not isinstance(asset, Mapping):
        raise MinecraftServerPackMigrationAdapterError(
            "NeoForge migration selection is missing its installer asset"
        )
    asset_sha = str(asset.get("sha256") or "").strip().lower()
    if not _SHA256.fullmatch(asset_sha):
        raise MinecraftServerPackMigrationAdapterError(
            "NeoForge installer selection is missing a trusted SHA256"
        )
    url = str(asset.get("url") or "").strip()
    expected_fragment = (
        "/net/neoforged/neoforge/"
        + build
        + "/neoforge-"
        + build
        + "-installer.jar"
    )
    if not url.startswith("https://maven.neoforged.net/") or expected_fragment not in url:
        raise MinecraftServerPackMigrationAdapterError(
            "NeoForge installer URL does not match the target build"
        )

    try:
        staged = stage_serverpack_archive(
            Path(archive),
            Path(stage_root),
            migration,
        )
    except Exception as exc:
        raise MinecraftServerPackMigrationAdapterError(str(exc)) from exc

    selected = dict(selection)
    selected["install_dir"] = install_dir
    return {
        "kind": "MinecraftServerPackMigrationPreparedInputs",
        "migration_plan_sha256": str(
            migration.get("migration_plan_sha256") or ""
        ).strip().lower(),
        "target_loader_version": build,
        "minecraft_version": version,
        "isolated_install_dir": install_dir,
        "runtime_selection": selected,
        "serverpack_staging": staged,
        "neoforge_installer_sha256": asset_sha,
        "execution_authorized": False,
    }


__all__ = [
    "MinecraftServerPackMigrationAdapterError",
    "prepare_migration_inputs",
]
