#!/usr/bin/env python3
"""Atomic publication bridge for deferred Minecraft Server Pack bundles."""
from __future__ import annotations

from typing import Any, Mapping

from content_repository import ContentRepository
from core.minecraft_serverpack_pending_commit import (
    MinecraftServerPackPendingCommitError,
    authorize_after_agent_completion,
)


class MinecraftServerPackPendingPublicationError(RuntimeError):
    pass


def publish_pending_serverpack_bundle(
    *,
    backend,
    session,
    request:Mapping[str,Any],
    result:Mapping[str,Any],
    instance_id:str,
) -> dict[str,Any] | None:
    configuration=request.get("configuration") if isinstance(request,Mapping) and isinstance(request.get("configuration"),Mapping) else {}
    pending=configuration.get("minecraft_serverpack_pending_bundle")
    if pending is None:
        return None
    if not isinstance(pending,Mapping):
        raise MinecraftServerPackPendingPublicationError(
            "pending Server Pack bundle contract is invalid"
        )
    try:
        authorized=authorize_after_agent_completion(pending,result)
    except MinecraftServerPackPendingCommitError as exc:
        raise MinecraftServerPackPendingPublicationError(str(exc)) from exc
    if str(authorized.get("instance_id") or "")!=str(instance_id or ""):
        raise MinecraftServerPackPendingPublicationError(
            "pending Server Pack instance differs from provisioning operation"
        )

    repo=ContentRepository(backend)
    ph=repo.ph
    current=session.execute(
        f"SELECT revision,manifest_sha256,minecraft_version,loader_id,loader_version "
        f"FROM content_bundles WHERE instance_id={ph} AND parent_content_id={ph}",
        (str(instance_id),str(authorized["content_id"])),
    ).fetchone()
    if current is None:
        raise MinecraftServerPackPendingPublicationError(
            "previous Server Pack bundle no longer exists"
        )
    expected=int(authorized["expected_previous_revision"])
    if int(current["revision"] or 0)!=expected:
        raise MinecraftServerPackPendingPublicationError(
            "Server Pack bundle revision changed while migration was running"
        )

    migration=result.get("minecraft_serverpack_migration")
    migration=migration if isinstance(migration,Mapping) else {}
    source_loader=str(migration.get("from_loader_version") or "").strip()
    target_loader=str(migration.get("target_loader_version") or "").strip()
    candidate_bundle=authorized.get("bundle")
    candidate_bundle=candidate_bundle if isinstance(candidate_bundle,Mapping) else {}
    target_minecraft=str(candidate_bundle.get("minecraft_version") or "").strip()
    if (
        not source_loader
        or not target_loader
        or str(current["loader_id"] or "").strip().lower()!="neoforge"
        or str(current["loader_version"] or "").strip()!=source_loader
        or str(candidate_bundle.get("loader_id") or "").strip().lower()!="neoforge"
        or str(candidate_bundle.get("loader_version") or "").strip()!=target_loader
        or not target_minecraft
    ):
        raise MinecraftServerPackPendingPublicationError(
            "Server Pack runtime identity changed while migration was running"
        )

    live=session.execute(
        f"SELECT runtime_id,game_version,build_id FROM instances WHERE id={ph}",
        (str(instance_id),),
    ).fetchone()
    if (
        live is None
        or str(live["runtime_id"] or "").strip()!="minecraft.java.neoforge"
        or str(live["game_version"] or "").strip()!=str(current["minecraft_version"] or "").strip()
        or str(live["game_version"] or "").strip()!=target_minecraft
        or str(live["build_id"] or "").strip()!=source_loader
    ):
        raise MinecraftServerPackPendingPublicationError(
            "instance runtime identity changed while migration was running"
        )

    published=repo.put_bundle_session(
        session,
        authorized["parent"],
        authorized["bundle"],
        authorized["children"],
        requested_by=str(authorized["requested_by"]),
        # This is completion of the already-serialized provisioning operation,
        # not a second customer write. The expected revision check above is the
        # concurrency gate; the normal customer modpack guard would otherwise
        # reject the in-flight parent that this very operation is completing.
        customer_install_guard=False,
    )
    if not published.get("changed"):
        raise MinecraftServerPackPendingPublicationError(
            "deferred Server Pack publication did not create a new revision"
        )
    if int(published.get("bundle_revision") or 0)!=expected+1:
        raise MinecraftServerPackPendingPublicationError(
            "deferred Server Pack publication revision is not sequential"
        )

    updated=session.execute(
        f"UPDATE instances SET game_version={ph},build_id={ph},updated_at={repo.dialect.current_timestamp} "
        f"WHERE id={ph} AND runtime_id={ph} AND game_version={ph} AND build_id={ph}",
        (
            target_minecraft,
            target_loader,
            str(instance_id),
            "minecraft.java.neoforge",
            target_minecraft,
            source_loader,
        ),
    )
    if int(getattr(updated,"rowcount",0) or 0)!=1:
        raise MinecraftServerPackPendingPublicationError(
            "instance runtime identity changed before Controller publication"
        )
    return {
        "kind":"MinecraftServerPackBundlePublication",
        "status":"published",
        "content_id":str(authorized["content_id"]),
        "transfer_id":str(authorized["transfer_id"]),
        "migration_plan_sha256":str(authorized["migration_plan_sha256"]),
        "candidate_sha256":str(authorized["candidate_sha256"]),
        "previous_bundle_revision":expected,
        "bundle_revision":int(published["bundle_revision"]),
        "manifest_sha256":str(published["manifest_sha256"]),
        "minecraft_version":target_minecraft,
        "from_loader_version":source_loader,
        "target_loader_version":target_loader,
        "instance_runtime_updated":True,
    }


__all__=[
    "MinecraftServerPackPendingPublicationError",
    "publish_pending_serverpack_bundle",
]
