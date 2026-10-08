#!/usr/bin/env python3
"""Strict contract for a future transactional NeoForge + Server Pack migration.

Validation only. This module deliberately does not authorize execution or mutate
instance/runtime state. Both Agents keep the executor fail-closed until the
transactional implementation is separately homologated.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_CONTENT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,191}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)+$")
_GAME_VERSION = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")


class MinecraftServerPackMigrationContractError(ValueError):
    pass


def _text(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    text = str(value or "").strip()
    if not pattern.fullmatch(text):
        raise MinecraftServerPackMigrationContractError(f"invalid {label}")
    return text


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise MinecraftServerPackMigrationContractError(f"invalid {label}")
    return text


def _loader(value: Any, label: str) -> str:
    return _text(value, label, _VERSION)


def _loader_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(piece) for piece in value.split("."))


def validate_minecraft_serverpack_migration(
    value: Mapping[str, Any],
    *,
    instance_id: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MinecraftServerPackMigrationContractError("migration contract must be an object")
    allowed = {
        "kind", "schema_version", "instance_id", "content_id", "transfer_id",
        "filename", "archive_sha256", "archive_size_bytes",
        "serverpack_prefix", "serverpack_mod_count", "serverpack_override_dirs",
        "migration_plan_sha256", "previous_bundle_revision",
        "previous_manifest_sha256", "from_loader_version",
        "target_loader_version", "minecraft_version", "isolated_install_dir",
        "backup_before_update", "preserve_world", "install_allowed",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise MinecraftServerPackMigrationContractError(
            "unsupported migration fields: " + ", ".join(unknown)
        )
    result = dict(value)
    if str(result.get("kind") or "") != "MinecraftServerPackMigration":
        raise MinecraftServerPackMigrationContractError("invalid migration kind")
    if int(result.get("schema_version") or 0) != 1:
        raise MinecraftServerPackMigrationContractError("unsupported migration schema")
    iid = _text(instance_id, "instance_id", _TOKEN)
    embedded_iid = _text(result.get("instance_id"), "migration.instance_id", _TOKEN)
    if embedded_iid != iid:
        raise MinecraftServerPackMigrationContractError("migration instance_id mismatch")
    result["instance_id"] = iid
    result["content_id"] = _text(result.get("content_id"), "content_id", _CONTENT_ID)
    result["transfer_id"] = _text(result.get("transfer_id"), "transfer_id", _TOKEN)
    filename = Path(str(result.get("filename") or "")).name
    if (
        not filename
        or filename != str(result.get("filename") or "")
        or not filename.lower().endswith(".zip")
    ):
        raise MinecraftServerPackMigrationContractError("invalid Server Pack filename")
    result["filename"] = filename
    result["archive_sha256"] = _sha(result.get("archive_sha256"), "archive_sha256")
    result["migration_plan_sha256"] = _sha(
        result.get("migration_plan_sha256"), "migration_plan_sha256"
    )
    result["previous_manifest_sha256"] = _sha(
        result.get("previous_manifest_sha256"), "previous_manifest_sha256"
    )
    try:
        archive_size = int(result.get("archive_size_bytes"))
        previous_revision = int(result.get("previous_bundle_revision"))
    except (TypeError, ValueError) as exc:
        raise MinecraftServerPackMigrationContractError(
            "invalid migration numeric evidence"
        ) from exc
    if archive_size <= 0 or previous_revision < 1:
        raise MinecraftServerPackMigrationContractError(
            "migration size/revision evidence must be positive"
        )
    result["archive_size_bytes"] = archive_size
    try:
        mod_count = int(result.get("serverpack_mod_count"))
    except (TypeError, ValueError) as exc:
        raise MinecraftServerPackMigrationContractError(
            "invalid Server Pack mod count"
        ) from exc
    if not 1 <= mod_count <= 1500:
        raise MinecraftServerPackMigrationContractError(
            "invalid Server Pack mod count"
        )
    result["serverpack_mod_count"] = mod_count
    prefix = str(result.get("serverpack_prefix") or "").strip()
    if prefix and (
        "/" in prefix
        or "\\" in prefix
        or prefix in {".", ".."}
        or any(not (c.isalnum() or c in "-_.") for c in prefix)
    ):
        raise MinecraftServerPackMigrationContractError(
            "invalid Server Pack wrapper"
        )
    result["serverpack_prefix"] = prefix
    roots = result.get("serverpack_override_dirs")
    if (
        not isinstance(roots, list)
        or len(roots) > 8
        or len(roots) != len(set(str(x) for x in roots))
    ):
        raise MinecraftServerPackMigrationContractError(
            "invalid Server Pack override directories"
        )
    allowed_roots = {
        "config", "defaultconfigs", "kubejs", "global_packs", "openloader",
        "crafttweaker", "scripts", "ftbquests", "resources",
    }
    cleaned_roots = [str(value or "").strip() for value in roots]
    if any(root not in allowed_roots for root in cleaned_roots):
        raise MinecraftServerPackMigrationContractError(
            "invalid Server Pack override directories"
        )
    result["serverpack_override_dirs"] = cleaned_roots
    result["previous_bundle_revision"] = previous_revision
    current = _loader(result.get("from_loader_version"), "from_loader_version")
    target = _loader(result.get("target_loader_version"), "target_loader_version")
    if _loader_tuple(target) <= _loader_tuple(current):
        raise MinecraftServerPackMigrationContractError(
            "target loader must be newer than installed loader"
        )
    result["from_loader_version"] = current
    result["target_loader_version"] = target
    result["minecraft_version"] = _text(
        result.get("minecraft_version"), "minecraft_version", _GAME_VERSION
    )
    result["isolated_install_dir"] = _text(
        result.get("isolated_install_dir"), "isolated_install_dir", _TOKEN
    )
    if result.get("backup_before_update") is not True:
        raise MinecraftServerPackMigrationContractError(
            "verified pre-update backup is mandatory"
        )
    if result.get("preserve_world") is not True:
        raise MinecraftServerPackMigrationContractError(
            "world preservation is mandatory"
        )
    if result.get("install_allowed") is not False:
        raise MinecraftServerPackMigrationContractError(
            "preview evidence must remain non-executable"
        )
    return result


__all__ = [
    "MinecraftServerPackMigrationContractError",
    "validate_minecraft_serverpack_migration",
]
