#!/usr/bin/env python3
"""Bounded, side-effect-free Agent heartbeat contract for committed Server Packs.

The Agent can request Controller proof for a completed, locally attested
migration. The response must match the same operation and manifest before
any local post-commit step is considered.
"""
from __future__ import annotations

from typing import Any, Mapping
from core.minecraft_serverpack_pending_commit import authorize_after_agent_completion


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
