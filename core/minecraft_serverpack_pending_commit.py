#!/usr/bin/env python3
"""Controller-side contract for deferred Server Pack bundle publication.

A future-loader Server Pack must not change content_assignments/content_bundles
when the customer confirms the preview. The complete candidate bundle is kept
inside the provisioning request as immutable pending evidence. Publication is
eligible only after the Agent returns a completed migration with the exact same
instance, content, transfer and migration fingerprint.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

_SHA256=re.compile(r"^[0-9a-f]{64}$")
_TOKEN=re.compile(r"^[A-Za-z0-9._:-]{1,191}$")


class MinecraftServerPackPendingCommitError(ValueError):
    pass


def _sha(value:Any,label:str)->str:
    text=str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise MinecraftServerPackPendingCommitError(f"invalid {label}")
    return text


def _token(value:Any,label:str)->str:
    text=str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise MinecraftServerPackPendingCommitError(f"invalid {label}")
    return text


def _canonical(value:Any)->str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)


def build_pending_bundle_commit(
    *,
    instance_id:str,
    content_id:str,
    transfer_id:str,
    migration_plan_sha256:str,
    expected_previous_revision:int,
    parent:Mapping[str,Any],
    bundle:Mapping[str,Any],
    children:list[Mapping[str,Any]],
    requested_by:str,
)->dict[str,Any]:
    iid=_token(instance_id,"instance_id")
    cid=_token(content_id,"content_id")
    tid=_token(transfer_id,"transfer_id")
    fingerprint=_sha(migration_plan_sha256,"migration_plan_sha256")
    try:
        previous=int(expected_previous_revision)
    except (TypeError,ValueError) as exc:
        raise MinecraftServerPackPendingCommitError(
            "invalid previous bundle revision"
        ) from exc
    if previous<1:
        raise MinecraftServerPackPendingCommitError(
            "previous bundle revision must be positive"
        )
    parent=dict(parent or {});bundle=dict(bundle or {})
    children=[dict(item or {}) for item in (children or [])]
    if str(parent.get("instance_id") or "")!=iid or str(parent.get("content_id") or "")!=cid:
        raise MinecraftServerPackPendingCommitError(
            "pending parent identity mismatch"
        )
    if str(bundle.get("parent_content_id") or cid)!=cid:
        # build_serverpack_bundle currently supplies the parent identity through
        # the ContentRepository call; tolerate omission, never mismatch.
        raise MinecraftServerPackPendingCommitError(
            "pending bundle parent identity mismatch"
        )
    if (
        str(parent.get("provider") or "").lower()!="local"
        or str(parent.get("content_type") or "").lower()!="modpack"
        or str(bundle.get("provider") or "").lower()!="local"
        or str(bundle.get("manifest_kind") or "").lower()!="serverpack-local-v1"
        or str(bundle.get("loader_id") or "").lower()!="neoforge"
    ):
        raise MinecraftServerPackPendingCommitError(
            "pending bundle is not an official local NeoForge Server Pack"
        )
    if not children:
        raise MinecraftServerPackPendingCommitError(
            "pending Server Pack must contain managed children"
        )
    child_ids=[]
    for child in children:
        if str(child.get("instance_id") or "")!=iid:
            raise MinecraftServerPackPendingCommitError(
                "pending bundle child instance mismatch"
            )
        child_id=_token(child.get("content_id"),"child content_id")
        if (
            str(child.get("provider") or "").lower()!="local"
            or str(child.get("content_type") or "").lower()!="mod"
            or str(child.get("target") or "")!=f"mods/{child_id}"
        ):
            raise MinecraftServerPackPendingCommitError(
                "pending Server Pack child is not a managed local mod"
            )
        if child_id==cid:
            raise MinecraftServerPackPendingCommitError(
                "pending bundle parent cannot be a child"
            )
        child_ids.append(child_id)
    if len(set(child_ids))!=len(child_ids):
        raise MinecraftServerPackPendingCommitError(
            "pending bundle contains duplicate children"
        )
    actor=str(requested_by or "").strip()[:191]
    if not actor:
        raise MinecraftServerPackPendingCommitError("requested_by is required")
    candidate={
        "instance_id":iid,
        "content_id":cid,
        "transfer_id":tid,
        "migration_plan_sha256":fingerprint,
        "expected_previous_revision":previous,
        "parent":parent,
        "bundle":bundle,
        "children":children,
        "requested_by":actor,
    }
    digest=hashlib.sha256(_canonical(candidate).encode("utf-8")).hexdigest()
    return {
        "kind":"MinecraftServerPackPendingBundleCommit",
        "schema_version":1,
        **candidate,
        "candidate_sha256":digest,
        "publish_allowed":False,
    }


def validate_pending_bundle_commit(value:Mapping[str,Any])->dict[str,Any]:
    if not isinstance(value,Mapping):
        raise MinecraftServerPackPendingCommitError(
            "pending bundle commit must be an object"
        )
    required={
        "kind","schema_version","instance_id","content_id","transfer_id",
        "migration_plan_sha256","expected_previous_revision","parent","bundle",
        "children","requested_by","candidate_sha256","publish_allowed",
    }
    if set(value)!=required:
        raise MinecraftServerPackPendingCommitError(
            "pending bundle commit fields differ from contract"
        )
    if value.get("kind")!="MinecraftServerPackPendingBundleCommit" or int(value.get("schema_version") or 0)!=1:
        raise MinecraftServerPackPendingCommitError(
            "unsupported pending bundle commit contract"
        )
    rebuilt=build_pending_bundle_commit(
        instance_id=str(value.get("instance_id") or ""),
        content_id=str(value.get("content_id") or ""),
        transfer_id=str(value.get("transfer_id") or ""),
        migration_plan_sha256=str(value.get("migration_plan_sha256") or ""),
        expected_previous_revision=int(value.get("expected_previous_revision") or 0),
        parent=value.get("parent") if isinstance(value.get("parent"),Mapping) else {},
        bundle=value.get("bundle") if isinstance(value.get("bundle"),Mapping) else {},
        children=value.get("children") if isinstance(value.get("children"),list) else [],
        requested_by=str(value.get("requested_by") or ""),
    )
    if str(value.get("candidate_sha256") or "").lower()!=rebuilt["candidate_sha256"]:
        raise MinecraftServerPackPendingCommitError(
            "pending bundle candidate checksum mismatch"
        )
    if value.get("publish_allowed") is not False:
        raise MinecraftServerPackPendingCommitError(
            "pending bundle must remain unpublished before Agent completion"
        )
    return rebuilt


def authorize_after_agent_completion(
    pending:Mapping[str,Any],
    result:Mapping[str,Any],
)->dict[str,Any]:
    candidate=validate_pending_bundle_commit(pending)
    if not isinstance(result,Mapping) or str(result.get("status") or "").lower()!="completed":
        raise MinecraftServerPackPendingCommitError(
            "Agent migration has not completed"
        )
    migration=result.get("minecraft_serverpack_migration")
    if not isinstance(migration,Mapping):
        raise MinecraftServerPackPendingCommitError(
            "completed provisioning result lacks migration evidence"
        )
    checks=(
        ("instance_id",candidate["instance_id"]),
        ("content_id",candidate["content_id"]),
        ("transfer_id",candidate["transfer_id"]),
        ("migration_plan_sha256",candidate["migration_plan_sha256"]),
    )
    for key,expected in checks:
        if str(migration.get(key) or "")!=str(expected):
            raise MinecraftServerPackPendingCommitError(
                f"completed Agent migration {key} mismatch"
            )
    if str(migration.get("status") or "").lower()!="completed":
        raise MinecraftServerPackPendingCommitError(
            "Agent migration detail is not completed"
        )
    commit=migration.get("commit")
    journal=commit.get("journal") if isinstance(commit,Mapping) and isinstance(commit.get("journal"),Mapping) else {}
    if str(journal.get("phase") or "")!="committed":
        raise MinecraftServerPackPendingCommitError(
            "Agent migration swap journal is not committed"
        )
    if str(journal.get("migration_plan_sha256") or "")!=candidate["migration_plan_sha256"]:
        raise MinecraftServerPackPendingCommitError(
            "Agent committed journal fingerprint mismatch"
        )
    return {
        **candidate,
        "publish_allowed":True,
        "agent_commit_verified":True,
    }


__all__=[
    "MinecraftServerPackPendingCommitError",
    "build_pending_bundle_commit",
    "validate_pending_bundle_commit",
    "authorize_after_agent_completion",
]
