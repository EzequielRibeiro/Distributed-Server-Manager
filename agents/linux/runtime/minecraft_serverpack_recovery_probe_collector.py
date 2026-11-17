#!/usr/bin/env python3
"""Bounded recovery probe collection from local completed provisioning history.

Read-only. No credential, database or filesystem mutation, and no attempt to
execute the recovery saga during heartbeat.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from minecraft_serverpack_recovery_heartbeat_contract import (
    build_recovery_probe,
    ServerPackHeartbeatContractError,
)


def latest_serverpack_recovery_probe(
    provisioning_root: Path,
    *,
    max_operations: int = 12,
) -> dict[str, str] | None:
    root = Path(provisioning_root)
    if not root.is_dir() or root.is_symlink():
        return None
    candidates: list[Path] = []
    for directory in (root, root / "history"):
        if not directory.is_dir() or directory.is_symlink():
            continue
        # Limited to a small number of recently archived operations.
        candidates.extend(path for path in directory.glob("*.result.json")
                          if path.is_file() and not path.is_symlink())
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for result_path in candidates[:max(1, min(max_operations, 20))]:
        job_id = result_path.name.removesuffix(".result.json")
        if not job_id.startswith("instance-provision-"):
            continue
        req_path = result_path.with_name(job_id + ".request.json")
        if not req_path.is_file() or req_path.is_symlink():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            request = json.loads(req_path.read_text(encoding="utf-8"))
            if not isinstance(result, dict) or not isinstance(request, dict):
                continue
            pending = (request.get("configuration") or {}).get(
                "minecraft_serverpack_pending_bundle")
            if not isinstance(pending, dict):
                continue
            migration = result.get("minecraft_serverpack_migration") or {}
            commit = migration.get("commit") if isinstance(migration, dict) else {}
            journal = commit.get("journal") if isinstance(commit, dict) else {}
            return build_recovery_probe(
                provisioning_id=job_id,
                pending=pending,
                agent_result=result,
                committed_journal=journal,
            )
        except (OSError, ValueError, TypeError, KeyError, ServerPackHeartbeatContractError):
            continue
    return None
