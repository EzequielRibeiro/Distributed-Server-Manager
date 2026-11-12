#!/usr/bin/env python3
"""Fail-closed, read-only physical attestation of a pending local Server Pack.

This verifies the managed mods directory, not the loader/startup or Controller
publication. It is deliberately independent of customer-facing projection state.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from content_bundle import normalize_bundle

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MinecraftServerPackPhysicalManifestError(ValueError):
    pass


def attest_serverpack_mods(runtime: Path, *, instance_id: str,
                           content_id: str, bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Prove that every active mods/*.jar matches the canonical manifest.

    Symlinks, hidden/non-JAR files, unknown JARs and changed sizes/hashes fail
    closed. Reads only; never deletes or alters a game file.
    """
    root = Path(runtime)
    if root.is_symlink() or not root.is_dir():
        raise MinecraftServerPackPhysicalManifestError("unsafe or missing runtime root")
    try:
        normalized = normalize_bundle({**dict(bundle),
            "instance_id": instance_id, "parent_content_id": content_id})
    except (ValueError, TypeError) as exc:
        raise MinecraftServerPackPhysicalManifestError("invalid authoritative Server Pack manifest") from exc
    if normalized["manifest_kind"] != "serverpack-local-v1":
        raise MinecraftServerPackPhysicalManifestError("not a local Server Pack manifest")
    entries = normalized["manifest"]["members"]
    expected: dict[str, tuple[str, int]] = {}
    for item in entries:
        path = str(item["path"])
        if not path.startswith("mods/") or path.count("/") != 1 or not path.endswith(".jar"):
            raise MinecraftServerPackPhysicalManifestError("manifest contains unsupported mod path")
        artifact = item["artifact"]
        sha = str(artifact.get("sha256") or "").lower()
        if not _SHA256.fullmatch(sha):
            raise MinecraftServerPackPhysicalManifestError("mod is missing SHA-256")
        expected[path.split("/", 1)[1]] = (sha, int(artifact["size_bytes"]))
    mods = root / "mods"
    if mods.is_symlink() or not mods.is_dir():
        raise MinecraftServerPackPhysicalManifestError("unsafe or missing mods directory")
    observed = {}
    for file in mods.iterdir():
        if file.is_symlink() or not file.is_file():
            raise MinecraftServerPackPhysicalManifestError("unsafe mod filesystem entry")
        if file.suffix.lower() != ".jar":
            raise MinecraftServerPackPhysicalManifestError("unexpected non-JAR in managed mods directory")
        if file.name not in expected:
            raise MinecraftServerPackPhysicalManifestError("unexpected managed JAR")
        sha, size = expected[file.name]
        if file.stat().st_size != size:
            raise MinecraftServerPackPhysicalManifestError("managed JAR size differs from manifest")
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != sha:
            raise MinecraftServerPackPhysicalManifestError("managed JAR SHA-256 differs from manifest")
        observed[file.name] = digest.hexdigest()
    if set(observed) != set(expected):
        raise MinecraftServerPackPhysicalManifestError("managed manifest members missing from runtime")
    return {"status": "physical_mods_verified",
            "manifest_sha256": normalized["manifest_sha256"],
            "mod_count": len(observed)}


__all__ = ["MinecraftServerPackPhysicalManifestError", "attest_serverpack_mods"]