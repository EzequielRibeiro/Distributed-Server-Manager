#!/usr/bin/env python3
"""Linux provisioning adapter for transactional Server Pack migrations.

Execution remains fail-closed behind the shared migration feature policy.
Homologation preserves the PR #855 identity gate. Production additionally
requires the explicit production acknowledgement and exact instance/Agent
allow-lists on this Agent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import time
from typing import Any
import zipfile
import sys

_AGENT_COMMON=Path(__file__).resolve().parents[2]/"common"
_PROJECT_ROOT=Path(__file__).resolve().parents[3]
for _path in (_AGENT_COMMON,_PROJECT_ROOT/"core"):
    if str(_path) not in sys.path:
        sys.path.insert(0,str(_path))

from adapters import resolve_adapter
from backup_client import _create as create_backup, _artifact as find_backup_artifact, MANIFEST_NAME
from content_upload_quarantine import quarantine_destination, validate_quarantine_archive
from game_data_executor import _execute as execute_game_data
import instance_runtime
from minecraft_serverpack_agent import verify_installed_neoforge
from minecraft_serverpack_controlled_stop import ensure_stopped
from minecraft_serverpack_migration_adapter import prepare_migration_inputs
from minecraft_serverpack_migration_contract import validate_minecraft_serverpack_migration
from minecraft_serverpack_migration_runtime_stage import build_staged_runtime
from minecraft_serverpack_migration_transaction import execute_minecraft_serverpack_migration
import minecraft_serverpack_migration_swap as migration_swap
from minecraft_staged_migration_safety import assess_staged_migration
from minecraft_serverpack_migration_feature import migration_feature_decision


class MinecraftServerPackProvisioningHomologationError(RuntimeError):
    pass


def _feature_for_request(request:dict[str,Any])->dict[str,Any]:
    return migration_feature_decision(
        instance_id=str(request.get("instance_id") or ""),
        agent_id=str(request.get("agent_id") or ""),
    )


def enabled_for(request:dict[str,Any])->bool:
    feature=_feature_for_request(request)
    if not feature["allowed"]:
        return False
    configuration=request.get("configuration")
    requested_mode=(
        str(configuration.get("minecraft_serverpack_execution_mode") or "").strip()
        if isinstance(configuration,dict)
        else ""
    )
    # Production must be explicitly bound into the Controller request so a
    # stale homologation request can never become executable after a config
    # change on the Agent. Homologation accepts the legacy request shape.
    if feature["mode"]=="production":
        return requested_mode=="production"
    return not requested_mode or requested_mode==feature["mode"]


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


def _attest_retained_backup(backup_id:Any,instance_id:str)->dict[str,Any]:
    """Resolve a backup by ID from the Agent-owned backup store and verify it."""
    if not isinstance(backup_id,str) or not backup_id.strip():
        raise MinecraftServerPackProvisioningHomologationError(
            "an Agent-owned retained backup ID is required before migration"
        )
    try:
        artifact=find_backup_artifact(instance_id,backup_id)
        if not artifact.is_file() or artifact.is_symlink():
            raise ValueError("unsafe backup artifact")
        size=artifact.stat().st_size
        if size<=0:
            raise ValueError("empty backup artifact")
        checksum=_digest(artifact)
        with tarfile.open(artifact,"r:*") as package:
            members=package.getmembers()
            manifest_member=next((item for item in members if item.name==MANIFEST_NAME),None)
            if manifest_member is None or not manifest_member.isfile():
                raise ValueError("backup manifest is missing")
            stream=package.extractfile(manifest_member)
            if stream is None:
                raise ValueError("backup manifest is unreadable")
            manifest=json.loads(stream.read().decode("utf-8"))
            if (
                manifest.get("kind")!="CapivaraInstanceBackup"
                or manifest.get("backup_format")!="capivara-instance"
                or manifest.get("backup_id")!=backup_id
                or manifest.get("source_instance")!=instance_id
            ):
                raise ValueError("backup manifest identity mismatch")
            if len(members)<=1:
                raise ValueError("backup contains no instance data")
            for member in members:
                if member.issym() or member.islnk() or member.isdev():
                    raise ValueError("backup contains unsafe filesystem entries")
                member_path=Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError("backup contains unsafe archive paths")
    except (OSError,ValueError,LookupError,tarfile.TarError,TypeError) as exc:
        raise MinecraftServerPackProvisioningHomologationError(
            "retained Agent backup failed independent verification"
        ) from exc
    return {
        "backup_id":backup_id,
        "sha256":checksum,
        "size_bytes":size,
        "integrity_verified":True,
    }


def _select_retained_backup_id(config:dict[str,Any],instance_id:str)->str:
    configured=config.get("minecraft_serverpack_retained_backup_id")
    if configured:
        return str(configured)
    # Discover only Agent-owned archives with a matching embedded manifest.
    # An invalid candidate is skipped; if none qualifies the capacity gate
    # fails closed before stopping the running server.
    from backup_client import BACKUP_ROOT
    directory=BACKUP_ROOT/instance_id
    if not directory.is_dir() or directory.is_symlink():
        raise MinecraftServerPackProvisioningHomologationError(
            "no trusted retained backup directory exists"
        )
    candidates=sorted(
        (p for p in directory.iterdir() if p.is_file() and not p.is_symlink()
         and (p.name.endswith(".tar.gz") or p.name.endswith(".tar"))),
        key=lambda p:p.stat().st_mtime,reverse=True,
    )
    for artifact in candidates:
        candidate_id=artifact.name[:-7] if artifact.name.endswith(".tar.gz") else artifact.name[:-4]
        try:
            _attest_retained_backup(candidate_id,instance_id)
            return candidate_id
        except (MinecraftServerPackProvisioningHomologationError,ValueError):
            continue
    raise MinecraftServerPackProvisioningHomologationError(
        "no verified retained Agent backup is available"
    )


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

    state:dict[str,Any]={}
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
        # Estimate backup from the existing runtime before stopping it.
        runtime_bytes=_tree_bytes(active)
        expanded=_expanded_zip_bytes(archive)
        return assess_staged_migration(
            available_bytes=shutil.disk_usage(instance_root).free,
            backup_bytes=runtime_bytes,
            serverpack_zip_bytes=archive.stat().st_size,
            expanded_pack_bytes=expanded,
            new_runtime_bytes=_tree_bytes(loader_seed)+expanded,
            # A size estimate is not evidence of an existing verified backup.
            # Fail closed until the Agent has independently attested the
            # retained baseline backup before starting the transaction.
            backup_evidence=_attest_retained_backup(
                _select_retained_backup_id(config,instance_id),instance_id
            ),
            plan_evidence={
                "migration_plan_sha256":evidence["migration_plan_sha256"],
                "install_allowed":False,
            },
        )

    def stop(evidence:dict[str,Any],backup_evidence:dict[str,Any])->None:
        state["stop_attempted"]=True
        state["initial_active_state"]=str(
            (adapter.status(record) or {}).get("active_state") or ""
        ).lower()
        state["controlled_stop"]=ensure_stopped(record,adapter)

    def backup(evidence:dict[str,Any])->dict[str,Any]:
        value=_verified_backup(config,instance_id)
        state["baseline_backup"]=value
        state["transaction_backup"]=value
        return value

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
            # A failed stop must propagate: swap commit or rollback cannot
            # proceed while the candidate server might still be running.
            ensure_stopped(active_record,adapter)

    def commit(evidence:dict[str,Any],backup_evidence:dict[str,Any])->dict[str,Any]:
        return migration_swap.commit(instance_root,readiness_passed=True)

    def rollback(evidence:dict[str,Any],backup_evidence:dict[str,Any],trace:tuple[str,...])->dict[str,Any]:
        # Never restore or restart while the candidate service may still be running.
        ensure_stopped(record,adapter)
        journal=instance_root/".dsm/minecraft-serverpack-migration.json"
        recovery=migration_swap.recover(instance_root) if journal.is_file() else {"status":"no_swap"}
        if state.get("initial_active_state") in {"active","activating"}:
            adapter.start(record)
        return recovery

    # Re-evaluate the complete local feature decision and Controller-bound
    # execution mode immediately before entering the transaction. This closes
    # a configuration TOCTOU window where an Agent policy change after initial
    # request validation could otherwise leave a stale mode executable.
    if not enabled_for(request):
        raise MinecraftServerPackProvisioningHomologationError(
            "Server Pack migration feature policy or execution mode changed before execution"
        )
    feature=_feature_for_request(request)
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
        "execution_mode":str(feature["mode"]),
        "homologation_only":bool(feature["homologation"]),
        "production_authorized":bool(feature["production"]),
        "quarantine_archive":str(archive),
        "target_loader_seed":str(loader_seed),
        "baseline_backup":{
            "backup_id":state["baseline_backup"]["backup_id"],
            "sha256":state["baseline_backup"]["sha256"],
            "size_bytes":state["baseline_backup"]["size_bytes"],
        },
        "candidate_runtime":state.get("candidate_runtime"),
    }


__all__=[
    "MinecraftServerPackProvisioningHomologationError",
    "enabled_for",
    "execute_homologated_migration",
]
