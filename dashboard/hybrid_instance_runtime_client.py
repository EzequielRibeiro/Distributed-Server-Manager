#!/usr/bin/env python3
"""Consume Controller instance lifecycle commands for the local Hybrid Agent."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from agent_instance_runtime_repository import AgentInstanceRuntimeRepository


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


def process_hybrid_instance_runtime_cycle(
    backend,
    root: Path,
    agent_id: str,
) -> dict[str, Any]:
    repository = AgentInstanceRuntimeRepository(backend)
    repository.initialize()

    command = repository.command_for_agent(agent_id)
    if not command:
        return {"status": "idle"}

    command_id = str(command["command_id"])
    repository.mark_delivered(command_id)

    _runtime_import(root)

    old_state = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
    os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(
        root / "runtime" / "hybrid-agent-state"
    )

    try:
        import instance_runtime

        config = _agent_config(root, agent_id)
        result = instance_runtime.handle_command(config, command)
        state = repository.apply_result(agent_id, result)
        return {
            "status": str(state.get("status") or result.get("status") or ""),
            "command_id": command_id,
            "instance_id": command.get("instance_id"),
            "action": command.get("action"),
            "result": result,
        }
    finally:
        if old_state is None:
            os.environ.pop("CAPIVARA_AGENT_STATE_DIR", None)
        else:
            os.environ["CAPIVARA_AGENT_STATE_DIR"] = old_state


__all__ = ["process_hybrid_instance_runtime_cycle"]
