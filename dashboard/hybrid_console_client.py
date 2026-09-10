#!/usr/bin/env python3
"""Consume game-console commands for the local Hybrid Agent."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from instance_workspace_repository import InstanceWorkspaceRepository


def _runtime_import(root: Path) -> None:
    runtime = root / "agents" / "linux" / "runtime"
    if str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))


def _agent_config(root: Path, agent_id: str) -> dict[str, Any]:
    path = root / "runtime" / "hybrid-agent-state" / "agent.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        value = {}

    config = value if isinstance(value, dict) else {}
    config["agent_id"] = agent_id
    return config


def process_hybrid_console_cycle(
    backend,
    root: Path,
    agent_id: str,
) -> dict[str, Any]:
    repository = InstanceWorkspaceRepository(backend)

    old_state = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
    os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(
        root / "runtime" / "hybrid-agent-state"
    )

    try:
        _runtime_import(root)
        import console_client

        # Recover a result left behind if the worker previously stopped
        # between local execution and Controller acknowledgement.
        pending = console_client.read_result()
        if isinstance(pending, dict):
            command_id = str(pending.get("command_id") or "")
            state = repository.apply_console_result(agent_id, pending)
            if command_id:
                console_client.clear_result(command_id)
            return {
                "status": str((state or {}).get("status") or pending.get("status") or ""),
                "command_id": command_id,
                "recovered": True,
            }

        command = repository.command_for_agent(agent_id)
        if not command:
            return {"status": "idle"}

        command_id = str(command.get("command_id") or "")
        repository.mark_console_delivered(command_id)

        result = console_client.handle_command(
            _agent_config(root, agent_id),
            command,
        )

        state = repository.apply_console_result(agent_id, result)
        console_client.clear_result(command_id)

        return {
            "status": str(
                (state or {}).get("status")
                or result.get("status")
                or ""
            ),
            "command_id": command_id,
            "instance_id": command.get("instance_id"),
            "result": result,
        }

    finally:
        if old_state is None:
            os.environ.pop("CAPIVARA_AGENT_STATE_DIR", None)
        else:
            os.environ["CAPIVARA_AGENT_STATE_DIR"] = old_state


__all__ = ["process_hybrid_console_cycle"]
