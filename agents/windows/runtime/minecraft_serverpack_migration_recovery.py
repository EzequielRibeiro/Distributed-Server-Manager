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
from minecraft_serverpack_migration_swap import recover as recover_swap


class MinecraftServerPackMigrationRecoveryError(RuntimeError):
    pass


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
            filesystem=recover_swap(Path(instance_state_root))
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
        }
        updated.pop("error",None)
        _atomic(_path(iid),updated)
        return {"status":"recovered","filesystem":filesystem,"operation":updated}


__all__=["MinecraftServerPackMigrationRecoveryError","recover_minecraft_serverpack_migration"]
