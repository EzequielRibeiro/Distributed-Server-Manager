#!/usr/bin/env python3
"""Fail-closed storage/readiness contract for staged Minecraft loader + pack migrations.

This module performs arithmetic and evidence checks only. It never authorizes
runtime mutation, accepts customer backup acknowledgments as proof, or creates
an executable provisioning request.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_SHA256 = re.compile(r"[0-9a-f]{64}")


class StagedMigrationSafetyError(ValueError):
    pass


def _positive_bytes(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StagedMigrationSafetyError(f"{label} must be a positive byte count")
    return value


def assess_staged_migration(
    *,
    available_bytes: int,
    backup_bytes: int,
    serverpack_zip_bytes: int,
    expanded_pack_bytes: int,
    new_runtime_bytes: int,
    backup_evidence: Mapping[str, Any],
    plan_evidence: Mapping[str, Any],
    required_headroom_bytes: int = 2 * 1024**3,
) -> dict[str, Any]:
    """Compute a conservative same-filesystem staging budget.

    Every value must be measured for the intended target volume. The estimate
    assumes a *new* full backup must fit alongside a retained rollback copy,
    uploaded ZIP, expanded content and isolated runtime. Unknown figures are
    blocking rather than silently guessed. This is a planning check, not a
    reservation: the eventual executor must remeasure inside its lock.
    """
    free = _positive_bytes(available_bytes, "available_bytes")
    existing_backup = _positive_bytes(backup_bytes, "backup_bytes")
    zip_size = _positive_bytes(serverpack_zip_bytes, "serverpack_zip_bytes")
    expanded = _positive_bytes(expanded_pack_bytes, "expanded_pack_bytes")
    runtime = _positive_bytes(new_runtime_bytes, "new_runtime_bytes")
    headroom = _positive_bytes(required_headroom_bytes, "required_headroom_bytes")
    if not isinstance(backup_evidence, Mapping) or not isinstance(plan_evidence, Mapping):
        raise StagedMigrationSafetyError("verifiable backup and plan evidence required")
    backup_sha = str(backup_evidence.get("sha256") or "").strip().lower()
    plan_sha = str(plan_evidence.get("migration_plan_sha256") or "").strip().lower()
    if not _SHA256.fullmatch(backup_sha) or not backup_evidence.get("backup_id"):
        raise StagedMigrationSafetyError("backup ID and SHA256 required")
    if backup_evidence.get("integrity_verified") is not True:
        raise StagedMigrationSafetyError("backup integrity must be independently verified")
    if not _SHA256.fullmatch(plan_sha):
        raise StagedMigrationSafetyError("staged migration fingerprint required")
    if plan_evidence.get("install_allowed") is not False:
        raise StagedMigrationSafetyError("preview must remain non-executable")
    # Reserve room for a second complete backup even if an older backup exists;
    # neither old backups nor the current world may be reclaimed to make room.
    required = existing_backup * 2 + zip_size + expanded + runtime + headroom
    return {
        "kind": "MinecraftStagedMigrationCapacityAssessment",
        "sufficient": free >= required,
        "available_bytes": free,
        "required_bytes": required,
        "shortfall_bytes": max(0, required - free),
        "backup_id": str(backup_evidence["backup_id"]),
        "migration_plan_sha256": plan_sha,
        "requires_exclusive_recheck": True,
        "install_allowed": False,
    }


def assess_separate_backup_volume(
    *,
    runtime_volume: Mapping[str, Any],
    backup_volume: Mapping[str, Any],
    new_backup_bytes: int,
    serverpack_zip_bytes: int,
    expanded_pack_bytes: int,
    new_runtime_bytes: int,
    backup_evidence: Mapping[str, Any],
    plan_evidence: Mapping[str, Any],
    headroom_bytes: int = 2 * 1024**3,
) -> dict[str, Any]:
    """Budget two separately mounted volumes; planning only, never approval.

    Existing verified backups are retained. The backup volume reserves room
    for one *additional* fresh full backup, while runtime volume needs space
    for ZIP, expanded modpack, isolated loader and its own safety headroom.
    Device IDs must be independently measured on the owning Agent.
    """
    if not isinstance(runtime_volume, Mapping) or not isinstance(backup_volume, Mapping):
        raise StagedMigrationSafetyError("both measured volumes are required")
    runtime_device = str(runtime_volume.get("device_id") or "").strip()
    backup_device = str(backup_volume.get("device_id") or "").strip()
    if not runtime_device or not backup_device or runtime_device == backup_device:
        raise StagedMigrationSafetyError("backup and runtime must have separate verified storage devices")
    runtime_free = _positive_bytes(runtime_volume.get("available_bytes"), "runtime.available_bytes")
    backup_free = _positive_bytes(backup_volume.get("available_bytes"), "backup.available_bytes")
    backup_required = _positive_bytes(new_backup_bytes, "new_backup_bytes")
    zip_size = _positive_bytes(serverpack_zip_bytes, "serverpack_zip_bytes")
    expanded = _positive_bytes(expanded_pack_bytes, "expanded_pack_bytes")
    isolated = _positive_bytes(new_runtime_bytes, "new_runtime_bytes")
    headroom = _positive_bytes(headroom_bytes, "headroom_bytes")
    if not isinstance(backup_evidence, Mapping) or not isinstance(plan_evidence, Mapping):
        raise StagedMigrationSafetyError("verified backup and migration evidence required")
    checksum = str(backup_evidence.get("sha256") or "").strip().lower()
    fingerprint = str(plan_evidence.get("migration_plan_sha256") or "").strip().lower()
    if (not str(backup_evidence.get("backup_id") or "").strip()
        or not _SHA256.fullmatch(checksum)
        or backup_evidence.get("integrity_verified") is not True):
        raise StagedMigrationSafetyError("an independently verified backup is mandatory")
    if not _SHA256.fullmatch(fingerprint) or plan_evidence.get("install_allowed") is not False:
        raise StagedMigrationSafetyError("a current non-executable migration plan is mandatory")
    runtime_required = zip_size + expanded + isolated + headroom
    backup_required += headroom
    return {
        "kind": "MinecraftStagedMigrationSeparateVolumeAssessment",
        "runtime_device_id": runtime_device,
        "backup_device_id": backup_device,
        "runtime_required_bytes": runtime_required,
        "runtime_available_bytes": runtime_free,
        "runtime_shortfall_bytes": max(0, runtime_required - runtime_free),
        "backup_required_bytes": backup_required,
        "backup_available_bytes": backup_free,
        "backup_shortfall_bytes": max(0, backup_required - backup_free),
        "sufficient": runtime_free >= runtime_required and backup_free >= backup_required,
        "requires_exclusive_recheck": True,
        "install_allowed": False,
    }
