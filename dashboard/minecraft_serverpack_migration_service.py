#!/usr/bin/env python3
"""Controller bridge from revalidated Server Pack preview to Agent provisioning.

This path is deliberately restricted to PR #855 homologation identities until
the full customer workflow is validated end-to-end. It freezes the candidate
bundle, resolves the exact NeoForge target from Catalog and enqueues one
provisioning request without publishing the new bundle revision.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from catalog_provisioning_resolver import resolve_catalog_provisioning
from customer_content_upload_service import CustomerContentUploadService
from customer_instance_workspace_service import CustomerInstanceWorkspaceService

_ENABLE_ENV="CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION"
_LAB_AGENT_ID="pr839-isolated-agent"
_INSTANCE_PREFIX="pr855-"


class MinecraftServerPackMigrationRequestError(RuntimeError):
    pass


def _isolated_install_dir(instance_id:str,runtime_id:str,version:str,build:str)->str:
    identity=hashlib.sha256(str(instance_id).encode("utf-8")).hexdigest()[:20]
    release=hashlib.sha256(
        f"{runtime_id}\0{version}\0{build}".encode("utf-8")
    ).hexdigest()[:12]
    return f"instance-{identity}-{release}"


def _homologation_allowed(context:Mapping[str,Any])->bool:
    return (
        os.environ.get(_ENABLE_ENV,"").strip().upper()=="YES"
        and str(context.get("id") or "").startswith(_INSTANCE_PREFIX)
        and str(context.get("agent_id") or "").strip()==_LAB_AGENT_ID
    )


class MinecraftServerPackMigrationService:
    def __init__(self,backend,root:Path):
        self.backend=backend
        self.root=Path(root)
        self.workspace=CustomerInstanceWorkspaceService(backend,self.root)
        self.uploads=CustomerContentUploadService(backend,self.root)

    def request(
        self,
        user:dict[str,Any],
        transfer_id:str,
        body:Mapping[str,Any],
        migration_plan_sha256:str,
    )->dict[str,Any]:
        if not isinstance(body,Mapping):
            raise MinecraftServerPackMigrationRequestError(
                "migration request payload must be an object"
            )
        instance_id=str(body.get("instance_id") or "").strip()
        if not instance_id:
            raise MinecraftServerPackMigrationRequestError("instance_id is required")

        # Require both content and runtime mutation permissions. The upload
        # preparation repeats content.install checks internally.
        context=self.workspace.require(user,instance_id,"instance.update")
        if str(context.get("game_id") or "").lower()!="minecraft":
            raise MinecraftServerPackMigrationRequestError(
                "Server Pack migration is available only for Minecraft"
            )
        runtime_id=str(context.get("runtime_id") or "").strip()
        if runtime_id!="minecraft.java.neoforge":
            raise MinecraftServerPackMigrationRequestError(
                "Server Pack loader migration requires the NeoForge runtime"
            )
        if not _homologation_allowed(context):
            raise MinecraftServerPackMigrationRequestError(
                "Server Pack migration provisioning remains restricted to PR855 homologation"
            )

        prepared=self.uploads.prepare_staged_loader_migration(
            user,transfer_id,body,migration_plan_sha256
        )
        migration_attestation=prepared.get("migration")
        pending=prepared.get("pending_bundle_commit")
        if not isinstance(migration_attestation,Mapping) or not isinstance(pending,Mapping):
            raise MinecraftServerPackMigrationRequestError(
                "prepared migration evidence is incomplete"
            )
        evidence=migration_attestation.get("evidence")
        if not isinstance(evidence,Mapping):
            raise MinecraftServerPackMigrationRequestError(
                "migration attestation has no immutable evidence"
            )

        target_version=str(evidence.get("minecraft_version") or "").strip()
        target_build=str(evidence.get("target_loader_version") or "").strip()
        from_build=str(evidence.get("from_loader_version") or "").strip()
        if (
            not target_version
            or not target_build
            or not from_build
            or str(context.get("build_id") or "").strip()!=from_build
        ):
            raise MinecraftServerPackMigrationRequestError(
                "live Minecraft loader identity changed since preview"
            )

        selector=f"{target_version}@{target_build}"
        selection,configuration=resolve_catalog_provisioning(
            environment_id=runtime_id,
            selector=selector,
            selection={},
            configuration={},
            root=self.root,
        )
        selection=dict(selection)
        isolated_dir=_isolated_install_dir(
            instance_id,runtime_id,target_version,target_build
        )
        selection["install_dir"]=isolated_dir

        migration={
            "kind":"MinecraftServerPackMigration",
            "schema_version":1,
            "instance_id":instance_id,
            "content_id":str(evidence.get("content_id") or ""),
            "transfer_id":str(evidence.get("transfer_id") or ""),
            "filename":str(evidence.get("filename") or ""),
            "archive_sha256":str(evidence.get("incoming_sha256") or ""),
            "archive_size_bytes":int(evidence.get("archive_size_bytes") or 0),
            "serverpack_prefix":str(evidence.get("serverpack_prefix") or ""),
            "serverpack_mod_count":int(evidence.get("serverpack_mod_count") or 0),
            "serverpack_override_dirs":list(
                evidence.get("serverpack_override_dirs") or []
            ),
            "migration_plan_sha256":str(
                migration_attestation.get("migration_plan_sha256") or ""
            ),
            "previous_bundle_revision":int(
                evidence.get("previous_bundle_revision") or 0
            ),
            "previous_manifest_sha256":str(
                evidence.get("previous_manifest_sha256") or ""
            ),
            "from_loader_version":from_build,
            "target_loader_version":target_build,
            "minecraft_version":target_version,
            "isolated_install_dir":isolated_dir,
            "backup_before_update":True,
            "preserve_world":True,
            "install_allowed":False,
        }
        configuration=dict(configuration or {})
        configuration["minecraft_serverpack_migration"]=migration
        configuration["minecraft_serverpack_pending_bundle"]=dict(pending)

        jobs=AgentInstanceProvisioningRepository(self.backend)
        jobs.initialize()
        state=jobs.enqueue(
            agent_id=str(context.get("agent_id") or ""),
            instance_id=instance_id,
            environment_id=runtime_id,
            selector=selector,
            selection=selection,
            configuration=configuration,
            desired_state="stopped",
            requested_by=str(user.get("username") or user.get("id") or "customer"),
        )

        queued=state.get("request") if isinstance(state.get("request"),Mapping) else {}
        queued_configuration=(
            queued.get("configuration")
            if isinstance(queued.get("configuration"),Mapping)
            else {}
        )
        queued_migration=queued_configuration.get("minecraft_serverpack_migration")
        queued_pending=queued_configuration.get("minecraft_serverpack_pending_bundle")
        if (
            not isinstance(queued_migration,Mapping)
            or not isinstance(queued_pending,Mapping)
            or str(queued_migration.get("migration_plan_sha256") or "")
               !=migration["migration_plan_sha256"]
            or str(queued_pending.get("candidate_sha256") or "")
               !=str(pending.get("candidate_sha256") or "")
        ):
            raise MinecraftServerPackMigrationRequestError(
                "instance already has a different active provisioning operation"
            )

        return {
            "accepted":True,
            "homologation_only":True,
            "instance_id":instance_id,
            "provisioning_id":str(state.get("provisioning_id") or ""),
            "status":str(state.get("status") or ""),
            "desired_state":"stopped",
            "migration":{
                "from_loader_version":from_build,
                "target_loader_version":target_build,
                "minecraft_version":target_version,
                "migration_plan_sha256":migration["migration_plan_sha256"],
            },
            "pending_bundle":{
                "content_id":str(pending.get("content_id") or ""),
                "candidate_sha256":str(pending.get("candidate_sha256") or ""),
                "expected_previous_revision":int(
                    pending.get("expected_previous_revision") or 0
                ),
                "candidate_bundle_revision":int(
                    prepared.get("candidate_bundle_revision") or 0
                ),
                "publish_allowed":False,
            },
        }


__all__=[
    "MinecraftServerPackMigrationRequestError",
    "MinecraftServerPackMigrationService",
]
