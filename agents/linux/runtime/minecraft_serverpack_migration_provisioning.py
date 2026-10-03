#!/usr/bin/env python3
"""Linux-only provisioning adapter for PR #855 isolated homologation.

This adapter intentionally refuses production-shaped instance IDs and is
disabled unless CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION=YES. It lets
the normal provisioning entry point exercise the already-homologated
transactional primitives on disposable/stopped node1 instances without making
the feature reachable for customer production instances.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tarfile
import time
from typing import Any
import zipfile

from adapters import resolve_adapter
from backup_client import _create as create_backup
from content_upload_quarantine import quarantine_destination, validate_quarantine_archive
from game_data_executor import _execute as execute_game_data
import instance_runtime
from minecraft_serverpack_agent import verify_installed_neoforge
from minecraft_serverpack_migration_adapter import prepare_migration_inputs
from minecraft_serverpack_migration_contract import validate_minecraft_serverpack_migration
from minecraft_serverpack_migration_runtime_stage import build_staged_runtime
from minecraft_serverpack_migration_transaction import execute_minecraft_serverpack_migration
import minecraft_serverpack_migration_swap as migration_swap
from minecraft_staged_migration_safety import assess_staged_migration


_ENABLE_ENV="CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION"
_PREFIX="pr855-"


class MinecraftServerPackProvisioningHomologationError(RuntimeError):
    pass


def enabled_for(request:dict[str,Any])->bool:
    return (
        os.environ.get(_ENABLE_ENV,"").strip().upper()=="YES"
        and str(request.get("instance_id") or "").startswith(_PREFIX)
    )


def _digest(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_bytes(root:Path)->int:
    total=0
    for current in root.rglob("*"):
        if current.is_symlink():
            raise MinecraftServerPackProvisioningHomologationError(
                "homologation runtime contains a symbolic link"
            )
        if current.is_file():
            total+=current.stat().st_size
    if total<=0:
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation runtime size is unavailable"
        )
    return total


def _expanded_zip_bytes(path:Path)->int:
    if not zipfile.is_zipfile(path):
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation Server Pack must be a ZIP"
        )
    with zipfile.ZipFile(path) as package:
        total=sum(max(0,int(info.file_size or 0)) for info in package.infolist())
    if total<=0:
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation Server Pack expanded size is unavailable"
        )
    return total


def _verified_backup(config:dict[str,Any],instance_id:str)->dict[str,Any]:
    created=create_backup(
        config,
        {
            "instance_id":instance_id,
            "policy":{
                "mode":"full",
                "compression":"gzip",
                "retention_count":7,
                "consistency":"stopped",
            },
        },
    )
    if not isinstance(created,dict):
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation backup returned invalid evidence"
        )
    artifact=Path(str(created.get("artifact_path") or ""))
    sha=str(created.get("sha256") or "").strip().lower()
    if (
        not artifact.is_file()
        or artifact.is_symlink()
        or len(sha)!=64
        or _digest(artifact)!=sha
        or int(created.get("size_bytes") or 0)<=0
    ):
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation backup integrity verification failed"
        )
    try:
        with tarfile.open(artifact,"r:*") as package:
            if not package.getmembers():
                raise MinecraftServerPackProvisioningHomologationError(
                    "homologation backup archive is empty"
                )
    except (tarfile.TarError,OSError) as exc:
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation backup archive cannot be verified"
        ) from exc
    return {**created,"integrity_verified":True}


def _wait_for_done(record:dict[str,Any],adapter:Any,*,timeout_seconds:int=240)->bool:
    working=Path(str(record.get("working_directory") or record.get("files_root") or ""))
    log=working/"logs/latest.log"
    started=time.monotonic()
    while time.monotonic()-started<timeout_seconds:
        state=adapter.status(record)
        active=str(state.get("active_state") or "").lower()
        if active=="failed":
            return False
        try:
            if log.is_file() and "Done (" in log.read_text(encoding="utf-8",errors="replace"):
                return active in {"active","activating"}
        except OSError:
            pass
        time.sleep(2)
    return False


def execute_homologated_migration(
    config:dict[str,Any],
    request:dict[str,Any],
)->dict[str,Any]:
    if not enabled_for(request):
        raise MinecraftServerPackProvisioningHomologationError(
            "Server Pack migration homologation gate is disabled"
        )
    instance_id=str(request.get("instance_id") or "")
    configuration=request.get("configuration")
    if not isinstance(configuration,dict):
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation provisioning configuration is required"
        )
    migration=validate_minecraft_serverpack_migration(
        configuration.get("minecraft_serverpack_migration"),
        instance_id=instance_id,
    )
    if str(request.get("desired_state") or "").lower()!="stopped":
        raise MinecraftServerPackProvisioningHomologationError(
            "PR855 homologation requires desired_state=stopped"
        )
    record=instance_runtime.get_instance(instance_id)
    if not isinstance(record,dict):
        raise MinecraftServerPackProvisioningHomologationError(
            "PR855 homologation requires an existing disposable instance"
        )
    if str(record.get("agent_id") or "")!=str(config.get("agent_id") or ""):
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation instance belongs to another Agent"
        )
    if str(record.get("environment_id") or "").lower()!="minecraft.java.neoforge":
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation instance must already use NeoForge"
        )
    instance_root=Path(str(record.get("instance_state_root") or ""))
    active=Path(str(record.get("working_directory") or record.get("files_root") or ""))
    if (
        not instance_root.is_absolute()
        or not active.is_absolute()
        or active.resolve()!=(instance_root/"runtime").resolve()
    ):
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation instance does not use a private runtime root"
        )
    adapter=resolve_adapter(record)
    status=adapter.status(record)
    if str(status.get("active_state") or "").lower() not in {"inactive","deactivating"}:
        raise MinecraftServerPackProvisioningHomologationError(
            "PR855 homologation currently requires the instance to be stopped"
        )
    current=verify_installed_neoforge(active,migration["from_loader_version"])
    if current.get("loader_version")!=migration["from_loader_version"]:
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation source loader differs from migration evidence"
        )

    archive=quarantine_destination(
        instance_id,
        migration["transfer_id"],
        migration["filename"],
    )
    inspection=validate_quarantine_archive(archive)
    if inspection.get("archive_type")!="zip":
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation Server Pack quarantine is not a ZIP"
        )
    if archive.stat().st_size!=migration["archive_size_bytes"] or _digest(archive)!=migration["archive_sha256"]:
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation quarantine differs from migration evidence"
        )

    content=request.get("content")
    selection=(content or {}).get("selection") if isinstance(content,dict) else None
    if not isinstance(selection,dict):
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation request requires a resolved NeoForge selection"
        )
    installed=execute_game_data({
        "action":str((content or {}).get("action") or "ensure"),
        "selection":dict(selection),
    })
    loader_seed=Path(str(installed.get("target_path") or ""))
    proof=verify_installed_neoforge(loader_seed,migration["target_loader_version"])
    if proof.get("loader_version")!=migration["target_loader_version"]:
        raise MinecraftServerPackProvisioningHomologationError(
            "homologation target loader installation is not attested"
        )

    baseline=_verified_backup(config,instance_id)
    state:dict[str,Any]={
        "baseline_backup":baseline,
        "loader_seed":str(loader_seed),
    }
    pack_stage=Path(str(configuration.get("minecraft_serverpack_homologation_stage") or (instance_root/".dsm/pr855-serverpack-stage")))
    candidate=instance_root/"runtime.migration-stage"

    def revalidate(evidence:dict[str,Any])->dict[str,Any]:
        if _digest(archive)!=evidence["archive_sha256"] or archive.stat().st_size!=evidence["archive_size_bytes"]:
            raise MinecraftServerPackProvisioningHomologationError(
                "quarantined Server Pack changed under migration lock"
            )
        verify_installed_neoforge(active,evidence["from_loader_version"])
        verify_installed_neoforge(loader_seed,evidence["target_loader_version"])
        return {
            "valid":True,
            "install_allowed":False,
            "migration_plan_sha256":evidence["migration_plan_sha256"],
        }

    def capacity(evidence:dict[str,Any])->dict[str,Any]:
        return assess_staged_migration(
            available_bytes=shutil.disk_usage(instance_root).free,
            backup_bytes=int(baseline["size_bytes"]),
            serverpack_zip_bytes=archive.stat().st_size,
            expanded_pack_bytes=_expanded_zip_bytes(archive),
            new_runtime_bytes=_tree_bytes(loader_seed)+_expanded_zip_bytes(archive),
            backup_evidence=baseline,
            plan_evidence={
                "migration_plan_sha256":evidence["migration_plan_sha256"],
                "install_allowed":False,
            },
        )

    def backup(evidence:dict[str,Any])->dict[str,Any]:
        value=_verified_backup(config,instance_id)
        state["transaction_backup"]=value
        return value

    def stop(evidence:dict[str,Any],backup_evidence:dict[str,Any])->None:
        current_state=adapter.status(record)
        if str(current_state.get("active_state") or "").lower() not in {"inactive","deactivating"}:
            raise MinecraftServerPackProvisioningHomologationError(
                "homologation instance became active before staging"
            )

    def stage(evidence:dict[str,Any],backup_evidence:dict[str,Any])->None:
        if pack_stage.exists():
            shutil.rmtree(pack_stage)
        prepared=prepare_migration_inputs(
            archive=archive,
            stage_root=pack_stage,
            migration=evidence,
            selection=selection,
        )
        built=build_staged_runtime(
            active_runtime=active,
            target_loader_seed=loader_seed,
            serverpack_stage=Path(prepared["serverpack_staging"]["stage_root"]),
            destination=candidate,
            target_loader_version=evidence["target_loader_version"],
        )
        state["prepared_inputs"]=prepared
        state["candidate_runtime"]=built
        migration_swap.prepare(
            instance_root,
            migration_plan_sha256=evidence["migration_plan_sha256"],
            target_loader_version=evidence["target_loader_version"],
            backup=backup_evidence,
        )

    def swap(evidence:dict[str,Any],backup_evidence:dict[str,Any])->None:
        migration_swap.switch(instance_root)

    def readiness(evidence:dict[str,Any],backup_evidence:dict[str,Any])->bool:
        active_record=dict(record)
        active_record["working_directory"]=str(active)
        active_record["files_root"]=str(active)
        try:
            adapter.start(active_record)
            ready=_wait_for_done(active_record,adapter)
            if ready:
                verify_installed_neoforge(active,evidence["target_loader_version"])
                ready=len(list((active/"mods").glob("*.jar")))==evidence["serverpack_mod_count"]
            return bool(ready)
        finally:
            try:
                current_state=adapter.status(active_record)
                if str(current_state.get("active_state") or "").lower() in {"active","activating"}:
                    adapter.stop(active_record)
            except Exception:
                pass

    def commit(evidence:dict[str,Any],backup_evidence:dict[str,Any])->dict[str,Any]:
        return migration_swap.commit(instance_root,readiness_passed=True)

    def rollback(evidence:dict[str,Any],backup_evidence:dict[str,Any],trace:tuple[str,...])->dict[str,Any]:
        try:
            current_state=adapter.status(record)
            if str(current_state.get("active_state") or "").lower() in {"active","activating"}:
                adapter.stop(record)
        except Exception:
            pass
        return migration_swap.recover(instance_root)

    result=execute_minecraft_serverpack_migration(
        config,
        instance_id,
        migration,
        {
            "revalidate":revalidate,
            "capacity":capacity,
            "backup":backup,
            "stop":stop,
            "stage":stage,
            "swap":swap,
            "readiness":readiness,
            "commit":commit,
            "rollback":rollback,
        },
    )
    return {
        **result,
        "homologation_only":True,
        "quarantine_archive":str(archive),
        "target_loader_seed":str(loader_seed),
        "baseline_backup":{
            "backup_id":baseline["backup_id"],
            "sha256":baseline["sha256"],
            "size_bytes":baseline["size_bytes"],
        },
        "candidate_runtime":state.get("candidate_runtime"),
    }


__all__=[
    "MinecraftServerPackProvisioningHomologationError",
    "enabled_for",
    "execute_homologated_migration",
]
