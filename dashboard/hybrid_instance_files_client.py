#!/usr/bin/env python3
"""Consume instance file commands for the local Hybrid Agent."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from instance_file_repository import InstanceFileRepository


FINAL_STATES = {"completed", "failed"}


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


def process_hybrid_instance_files_cycle(
    backend,
    root: Path,
    agent_id: str,
    *,
    max_commands: int = 8,
) -> dict[str, Any]:

    repository = InstanceFileRepository(backend)
    state_dir = root / "runtime" / "hybrid-agent-state"

    _runtime_import(root)

    old_state = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
    os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(state_dir)

    processed = []

    try:
        import instance_files_client

        config = _agent_config(root, agent_id)

        # Recover one result that may have survived a worker interruption.
        recovered = instance_files_client.read_result()

        if isinstance(recovered, dict):
            command_id = str(recovered.get("command_id") or "").strip()

            if command_id:
                try:
                    current = repository.snapshot(command_id)
                except KeyError:
                    instance_files_client.clear_result(command_id)
                else:
                    if str(current.get("status") or "") in FINAL_STATES:
                        instance_files_client.clear_result(command_id)
                    else:
                        applied = repository.apply_result(agent_id, recovered)
                        instance_files_client.clear_result(command_id)
                        processed.append({
                            "command_id": command_id,
                            "instance_id": recovered.get("instance_id"),
                            "action": recovered.get("action"),
                            "status": applied.get("status") if applied else None,
                            "recovered": True,
                        })

        limit = max(1, min(int(max_commands), 32))

        while len(processed) < limit:
            command = repository.command_for_agent(agent_id)

            if not isinstance(command, dict):
                break

            report = instance_files_client.handle_command(config, command)
            applied = repository.apply_result(agent_id, report)

            command_id = str(command.get("command_id") or "")
            if command_id:
                instance_files_client.clear_result(command_id)

            processed.append({
                "command_id": command_id,
                "instance_id": command.get("instance_id"),
                "action": command.get("action"),
                "status": applied.get("status") if applied else None,
                "recovered": False,
            })

        if not processed:
            return {"state": "idle", "processed": 0}

        return {
            "state": "processed",
            "processed": len(processed),
            "commands": processed,
        }

    finally:
        if old_state is None:
            os.environ.pop("CAPIVARA_AGENT_STATE_DIR", None)
        else:
            os.environ["CAPIVARA_AGENT_STATE_DIR"] = old_state


__all__ = ["process_hybrid_instance_files_cycle"]
