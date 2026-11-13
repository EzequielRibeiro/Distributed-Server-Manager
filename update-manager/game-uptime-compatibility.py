#!/usr/bin/env python3
"""Fail-closed Controller/Agent and Minecraft supervisor compatibility assessment.

This is a read-only contract check, NOT an authorization to skip game drain.
Unknown/missing declarations, process identity changes and replaceable supervisor
code are blocking. A separate updater transaction and live E2E are required.
"""
from __future__ import annotations
from pathlib import Path
from typing import Mapping, Any
import hashlib

SUPERVISOR_RELATIVE = "agents/linux/runtime/console_supervisor.py"
CONTRACT_FIELDS = ("protocol", "schema", "controller_api", "agent_api")


def _digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("supervisor file missing or unsafe")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assess(installed: Path, target: Path, controller: Mapping[str, Any] | None,
           agent: Mapping[str, Any] | None, *, minecraft_active: bool = True,
           supervisor_pinned: bool = False) -> dict[str, Any]:
    """Require exact declared compatibility and an immutable running supervisor.

    An immutable supervisor needs a separate, verified lifecycle-independent
    executable, kept until all processes using it exit; a matching hash alone
    is not sufficient to prove that the Python process will survive an update.
    """
    blockers: list[str] = []
    if not isinstance(controller, Mapping) or not isinstance(agent, Mapping):
        blockers.append("controller_agent_contract_missing")
    else:
        for field in CONTRACT_FIELDS:
            left, right = controller.get(field), agent.get(field)
            if not isinstance(left, str) or not left.strip() or left != right:
                blockers.append("controller_agent_" + field + "_mismatch")
    try:
        before = _digest(installed / SUPERVISOR_RELATIVE)
        after = _digest(target / SUPERVISOR_RELATIVE)
        changed = before != after
    except (OSError, ValueError):
        changed = True
        blockers.append("minecraft_supervisor_unverifiable")
    if minecraft_active and changed and not supervisor_pinned:
        blockers.append("minecraft_live_supervisor_replaceable")
    if minecraft_active and not supervisor_pinned:
        blockers.append("minecraft_supervisor_lifecycle_not_isolated")
    return {
        "kind": "CapivaraNoDrainCompatibility",
        "schema_version": 1,
        "mode": "read_only",
        "controller_agent_compatible": not any(x.startswith("controller_agent_") for x in blockers),
        "minecraft_supervisor_changed": changed,
        "minecraft_supervisor_pinned": bool(supervisor_pinned),
        "blockers": sorted(set(blockers)),
        "compatible_for_further_rehearsal": not blockers,
        "live_no_drain_authorized": False,
    }
