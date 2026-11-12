#!/usr/bin/env python3
"""Bounded, side-effect-free Agent heartbeat contract for committed Server Packs.

The Agent can request Controller proof for a completed, locally attested
migration. The response must match the same operation and manifest before
any local post-commit step is considered.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


# The Linux Agent package intentionally does not ship Controller core/.
# Reproduce the canonical pending-candidate digest locally, then require
# proof of the exact committed Agent swap. Never trust a caller-supplied SHA.
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,191}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset({
    "kind", "schema_version", "instance_id", "content_id", "transfer_id",
    "migration_plan_sha256", "expected_previous_revision", "parent",
    "bundle", "children", "requested_by", "candidate_sha256", "publish_allowed",
})


def authorize_after_agent_completion(pending: Mapping[str, Any],
                                     result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(pending, Mapping) or set(pending) != _FIELDS:
        raise ValueError("invalid pending contract fields")
    if (pending.get("kind") != "MinecraftServerPackPendingBundleCommit"
            or pending.get("schema_version") != 1
            or pending.get("publish_allowed") is not False):
        raise ValueError("unverified pending contract")
    for name in ("instance_id", "content_id", "transfer_id"):
        if not isinstance(pending.get(name), str) or not _ID.fullmatch(pending[name]):
            raise ValueError("invalid pending identity")
    if (not isinstance(pending.get("migration_plan_sha256"), str)
            or not _SHA.fullmatch(pending["migration_plan_sha256"])):
        raise ValueError("invalid migration fingerprint")
    previous = pending.get("expected_previous_revision")
    if not isinstance(previous, int) or isinstance(previous, bool) or previous < 1:
        raise ValueError("invalid previous bundle revision")
    parent = pending.get("parent")
    bundle = pending.get("bundle")
    children = pending.get("children")
    if not (isinstance(parent, Mapping) and isinstance(bundle, Mapping)
            and isinstance(children, list) and len(children) > 0):
        raise ValueError("invalid pending Server Pack manifest")
    if (parent.get("instance_id") != pending["instance_id"]
            or parent.get("content_id") != pending["content_id"]
            or parent.get("provider") != "local"
            or parent.get("content_type") != "modpack"
            or bundle.get("provider") != "local"
            or bundle.get("manifest_kind") != "serverpack-local-v1"
            or bundle.get("loader_id") != "neoforge"):
        raise ValueError("unexpected Server Pack parent or loader")
    ids = set()
    for child in children:
        if not isinstance(child, Mapping):
            raise ValueError("invalid managed child")
        cid = child.get("content_id")
        if not isinstance(cid, str) or not _ID.fullmatch(cid) or cid in ids:
            raise ValueError("invalid or duplicated managed child")
        ids.add(cid)
        if (child.get("instance_id") != pending["instance_id"]
                or child.get("provider") != "local"
                or child.get("content_type") != "mod"
                or child.get("target") != f"mods/{cid}"):
            raise ValueError("unexpected Server Pack child")
    members = bundle.get("members")
    if not isinstance(members, list) or len(members) != len(ids):
        raise ValueError("invalid bundle member inventory")
    if {item.get("content_id") for item in members
            if isinstance(item, Mapping)} != ids:
        raise ValueError("bundle member mismatch")
    if not str(pending.get("requested_by") or "").strip():
        raise ValueError("missing request actor")
    candidate = {key: pending[key] for key in (
        "instance_id", "content_id", "transfer_id", "migration_plan_sha256",
        "expected_previous_revision", "parent", "bundle", "children", "requested_by",
    )}
    digest = hashlib.sha256(json.dumps(
        candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    if pending.get("candidate_sha256") != digest:
        raise ValueError("candidate manifest checksum mismatch")
    if not isinstance(result, Mapping) or result.get("status") != "completed":
        raise ValueError("Agent migration not completed")
    migration = result.get("minecraft_serverpack_migration")
    if not isinstance(migration, Mapping) or migration.get("status") != "completed":
        raise ValueError("Agent migration evidence absent")
    for key in ("instance_id", "content_id", "transfer_id", "migration_plan_sha256"):
        if migration.get(key) != pending[key]:
            raise ValueError("migration identity or fingerprint mismatch")
    commit = migration.get("commit")
    journal = commit.get("journal") if isinstance(commit, Mapping) else None
    if (not isinstance(journal, Mapping)
            or journal.get("phase") != "committed"
            or journal.get("migration_plan_sha256") != pending["migration_plan_sha256"]):
        raise ValueError("migration journal is not committed")
    return dict(pending)


class ServerPackHeartbeatContractError(ValueError):
    pass


def build_recovery_probe(
    *, provisioning_id: str,
    pending: Mapping[str, Any],
    agent_result: Mapping[str, Any],
    committed_journal: Mapping[str, Any],
) -> dict[str, str]:
    try:
        evidence = authorize_after_agent_completion(pending, agent_result)
    except (ValueError, KeyError, TypeError) as exc:
        raise ServerPackHeartbeatContractError("Agent migration has no verified commit") from exc
    if not isinstance(provisioning_id, str) or not provisioning_id.startswith("instance-provision-"):
        raise ServerPackHeartbeatContractError("invalid provisioning identifier")
    if agent_result.get("provisioning_id") != provisioning_id:
        raise ServerPackHeartbeatContractError("local result is for another provisioning")
    if agent_result.get("instance_id") != evidence["instance_id"]:
        raise ServerPackHeartbeatContractError("local result is for another instance")
    if not isinstance(committed_journal, Mapping) or (
        committed_journal.get("phase") != "committed"
        or committed_journal.get("migration_plan_sha256") != evidence["migration_plan_sha256"]
        or committed_journal.get("target_loader_version") != evidence["bundle"]["loader_version"]
    ):
        raise ServerPackHeartbeatContractError("local durable journal has not committed")
    return {
        "provisioning_id": provisioning_id,
        "instance_id": evidence["instance_id"],
        "candidate_sha256": evidence["candidate_sha256"],
    }


def verify_recovery_offer(
    probe: Mapping[str, Any],
    offer: Mapping[str, Any],
    pending: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(probe, Mapping) or not isinstance(offer, Mapping):
        raise ServerPackHeartbeatContractError("missing recovery offer")
    if not isinstance(pending, Mapping):
        raise ServerPackHeartbeatContractError("missing pending Server Pack")
    expected = {
        "kind": "ServerPackRecoveryOffer",
        "status": "verified",
        "provisioning_id": probe.get("provisioning_id"),
        "instance_id": probe.get("instance_id"),
        "candidate_sha256": probe.get("candidate_sha256"),
        "bundle_revision": pending.get("expected_previous_revision", 0) + 1,
        "loader_version": (pending.get("bundle") or {}).get("loader_version"),
        "child_count": len(pending.get("children") or ()),
        "instruction": "verify_local_sources_before_recovery",
    }
    if not all(offer.get(k) == v for k,v in expected.items()):
        raise ServerPackHeartbeatContractError("Controller offer mismatches locally committed candidate")
    sha = offer.get("manifest_sha256")
    if not isinstance(sha,str) or len(sha)!=64 or any(c not in "0123456789abcdef" for c in sha):
        raise ServerPackHeartbeatContractError("Controller manifest checksum invalid")
    return {
        "kind": "VerifiedServerPackRecoveryOffer",
        "status": "verified",
        "instance_id": expected["instance_id"],
        "provisioning_id": expected["provisioning_id"],
        "candidate_sha256": expected["candidate_sha256"],
        "bundle_revision": expected["bundle_revision"],
        "manifest_sha256": sha,
        "loader_version": expected["loader_version"],
        "child_count": expected["child_count"],
    }
