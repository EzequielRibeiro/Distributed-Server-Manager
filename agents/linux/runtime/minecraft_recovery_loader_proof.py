"""Read-only current NeoForge proof bound to the installed Agent registry."""
from __future__ import annotations
from pathlib import Path
import sys
_COMMON = Path(__file__).resolve().parents[2] / 'common'
if str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))
from typing import Any
from minecraft_serverpack_agent import verify_installed_neoforge


def verify_recovered_loader(
    record: dict[str, Any] | None,
    recovery: dict[str, Any] | None,
    *, instance_id: str, agent_id: str,
) -> dict[str, Any] | None:
    if not isinstance(record, dict) or not isinstance(recovery, dict):
        return None
    if record.get("instance_id") != instance_id or record.get("agent_id") != agent_id:
        return None
    if recovery.get("instance_id") != instance_id or recovery.get("agent_id") != agent_id:
        return None
    if recovery.get("status") != "recovered" or recovery.get("operation") != "minecraft_serverpack_migration":
        return None
    detail = recovery.get("recovery")
    if not isinstance(detail, dict) or detail.get("manual_recovery_required") is not False:
        return None
    version = detail.get("original_loader_version")
    base = Path(str(record.get("working_directory") or ""))
    if not isinstance(version, str) or not base.is_absolute() or base.is_symlink() or not base.is_dir():
        return None
    try:
        proof = verify_installed_neoforge(base, version)
    except (ValueError, OSError):
        return None
    return {"instance_id": instance_id, "agent_id": agent_id,
            "loader_version": version, "verified": True, "evidence": proof.get("evidence")}
