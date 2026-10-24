"""Read-only *current* NeoForge attestation; never reconstructs recovery history."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from minecraft_recovery_loader_proof import verify_installed_neoforge


def attest_current_neoforge(record: dict[str, Any] | None, *,
                            instance_id: str, agent_id: str,
                            expected_version: str) -> dict[str, Any] | None:
    if not isinstance(record, dict) or record.get("instance_id") != instance_id or record.get("agent_id") != agent_id:
        return None
    if not isinstance(expected_version, str) or not expected_version or any(
        c not in "0123456789." for c in expected_version
    ):
        return None
    raw = record.get("working_directory")
    if not isinstance(raw, str) or not raw:
        return None
    base = Path(raw)
    if not base.is_absolute() or base.is_symlink() or not base.is_dir():
        return None
    try:
        checked = verify_installed_neoforge(base, expected_version)
    except (ValueError, OSError):
        return None
    if not isinstance(checked, dict) or not checked.get("evidence"):
        return None
    return {"kind": "MinecraftNeoForgeCurrentAttestation",
            "instance_id": instance_id, "agent_id": agent_id,
            "loader_version": expected_version, "verified": True,
            "evidence": checked["evidence"]}
