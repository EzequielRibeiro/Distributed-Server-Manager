"""Dedicated recovery coordinator for interrupted staged Minecraft migrations.

This is the only path allowed to clear the outer runtime-operation barrier after
the migration-specific filesystem journal proves the original runtime has been
restored. It never treats a committed migration as a rollback candidate.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_AGENT_COMMON=Path(__file__).resolve().parents[2]/"common"
if str(_AGENT_COMMON) not in sys.path:sys.path.insert(0,str(_AGENT_COMMON))

import instance_runtime
from runtime_lock import instance_lock
from runtime_operations import _atomic, _now, _path, read_operation
from privileged_materialization import minecraft_serverpack_swap_phase
from minecraft_serverpack_agent import verify_installed_neoforge


class MinecraftServerPackMigrationRecoveryError(RuntimeError):
    pass


def _prove_pre_swap_failure(outer:dict[str,Any],record:dict[str,Any],root:Path)->dict[str,Any]:
    """Fail closed unless a known pre-swap permission failure left original loader intact.

    The outer journal is retained for audit. No game file is modified.
    This is not an alternative to recovering a missing/failed swap journal.
    """
    if outer.get("status")!="failed":
        raise MinecraftServerPackMigrationRecoveryError("pre-swap recovery requires a failed operation")
    error=str(outer.get("error") or "")
    if (not (("Permission denied" in error and "runtime.migration-stage" in error) or "quarantined content archive is unavailable" in error)
            or not error.startswith("migration transaction stopped:")):
        raise MinecraftServerPackMigrationRecoveryError("pre-swap failure is not a recognized safe failure")
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise MinecraftServerPackMigrationRecoveryError("unsafe instance root")
    runtime=root/"runtime"
    if runtime.is_symlink() or not runtime.is_dir():
        raise MinecraftServerPackMigrationRecoveryError("original runtime is absent or unsafe")
    if Path(str(record.get("working_directory") or ""))!=runtime:
        raise MinecraftServerPackMigrationRecoveryError("active runtime does not match registered working directory")
    control=root/".dsm"
    if control.is_symlink() or (control.exists() and not control.is_dir()):
        raise MinecraftServerPackMigrationRecoveryError("unsafe migration control directory")
    paths=[root/"runtime.migration-stage",root/"runtime.migration-rollback",
           root/"runtime.migration-failed",control/"minecraft-serverpack-migration.json",
           control/".minecraft-serverpack-migration.json.tmp"]
    if any(path.exists() or path.is_symlink() for path in paths):
        raise MinecraftServerPackMigrationRecoveryError("filesystem transaction evidence exists: require normal recovery")
    version=str(record.get("build_id") or "").strip()
    try:
        if not version:
            # The provisioned Agent registry does not always retain build_id.
            # Derive only an unambiguous installed candidate, then require the
            # same strong launcher/canonical-args verification as normal.
            libraries=runtime/"libraries/net/neoforged/neoforge"
            if libraries.is_symlink() or not libraries.is_dir():
                raise ValueError("NeoForge libraries missing or unsafe")
            candidates=list(libraries.iterdir())
            if len(candidates)!=1 or candidates[0].is_symlink() or not candidates[0].is_dir():
                raise ValueError("NeoForge loader identity is ambiguous")
            version=candidates[0].name
        proof=verify_installed_neoforge(runtime,version)
    except (ValueError,OSError) as exc:
        raise MinecraftServerPackMigrationRecoveryError("original NeoForge loader cannot be verified") from exc
    return {"status":"recovered","pre_swap_only":True,"failed_runtime_retained":False,
            "original_loader_version":proof["loader_version"],
            "reason":"verified_pre_swap_failure"}


def recover_minecraft_serverpack_migration(
    config:dict[str,Any],
    instance_id:str,
    *,
    instance_state_root:Path,
    lock_timeout_seconds:float=5.0,
)->dict[str,Any]:
    agent_id=str(config.get("agent_id") or "").strip()
    if not agent_id:
        raise MinecraftServerPackMigrationRecoveryError("agent_id is required")
    iid=instance_runtime._token(instance_id,"instance_id")
    with instance_lock(iid,"minecraft_serverpack_migration_recovery",timeout_seconds=lock_timeout_seconds):
        outer=read_operation(iid)
        if outer is None:
            if _path(iid).exists():
                raise MinecraftServerPackMigrationRecoveryError(
                    "instance operation journal is unreadable; manual recovery required"
                )
            raise MinecraftServerPackMigrationRecoveryError(
                "no staged migration operation journal exists"
            )
        if str(outer.get("agent_id") or "")!=agent_id:
            raise MinecraftServerPackMigrationRecoveryError(
                "migration operation belongs to another Agent"
            )
        if outer.get("operation")!="minecraft_serverpack_migration":
            raise MinecraftServerPackMigrationRecoveryError(
                "latest instance operation is not a staged Minecraft migration"
            )
        if outer.get("status")=="recovered":
            return {"status":"already_recovered","operation":dict(outer)}
        if outer.get("status") not in {"failed","interrupted"}:
            raise MinecraftServerPackMigrationRecoveryError(
                "migration operation is not eligible for recovery"
            )

        try:
            record=instance_runtime._owned(config,iid)
            if Path(str(record.get("instance_state_root") or ""))!=Path(instance_state_root):
                raise MinecraftServerPackMigrationRecoveryError("recovery instance root differs from registered runtime")
            root=Path(instance_state_root)
            control=root/".dsm"
            swap_journal=control/"minecraft-serverpack-migration.json"
            swap_temp=control/".minecraft-serverpack-migration.json.tmp"
            if swap_journal.exists() or swap_journal.is_symlink() or swap_temp.exists() or swap_temp.is_symlink():
                filesystem=minecraft_serverpack_swap_phase(config,record,"recover")
            elif (outer.get("status")=="failed" and
                  str(outer.get("error") or "").startswith("migration transaction stopped:") and
                  "Permission denied" in str(outer.get("error") or "") and
                  "runtime.migration-stage" in str(outer.get("error") or "")):
                filesystem=_prove_pre_swap_failure(outer,record,root)
            else:
                filesystem=minecraft_serverpack_swap_phase(config,record,"recover")
        except Exception as exc:
            raise MinecraftServerPackMigrationRecoveryError(
                "filesystem recovery could not prove restoration of the original runtime"
            ) from exc
        if str(filesystem.get("status") or "") not in {"recovered","already_recovered"}:
            raise MinecraftServerPackMigrationRecoveryError(
                "filesystem recovery returned an invalid result"
            )

        updated=dict(outer)
        updated["status"]="recovered"
        updated["recovered_at"]=_now()
        updated["recovery"]={
            "kind":"MinecraftServerPackMigrationRecovery",
            "filesystem_status":str(filesystem.get("status") or ""),
            "failed_runtime_retained":bool(filesystem.get("failed_runtime_retained")),
            "manual_recovery_required":False,
            "pre_swap_only":bool(filesystem.get("pre_swap_only")),
            "original_loader_version":filesystem.get("original_loader_version"),
        }
        updated.pop("error",None)
        _atomic(_path(iid),updated)
        return {"status":"recovered","filesystem":filesystem,"operation":updated}


__all__=["MinecraftServerPackMigrationRecoveryError","recover_minecraft_serverpack_migration"]
