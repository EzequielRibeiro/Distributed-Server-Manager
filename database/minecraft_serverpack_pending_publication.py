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
        f"SELECT revision,manifest_sha256 FROM content_bundles "
        f"WHERE instance_id={ph} AND parent_content_id={ph}",
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

    published=repo.put_bundle_session(
        session,
        authorized["parent"],
        authorized["bundle"],
        authorized["children"],
        requested_by=str(authorized["requested_by"]),
        customer_install_guard=True,
    )
    if not published.get("changed"):
        raise MinecraftServerPackPendingPublicationError(
            "deferred Server Pack publication did not create a new revision"
        )
    if int(published.get("bundle_revision") or 0)!=expected+1:
        raise MinecraftServerPackPendingPublicationError(
            "deferred Server Pack publication revision is not sequential"
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
    }


__all__=[
    "MinecraftServerPackPendingPublicationError",
    "publish_pending_serverpack_bundle",
]
