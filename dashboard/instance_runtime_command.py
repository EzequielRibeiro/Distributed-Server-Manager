#!/usr/bin/env python3
"""Synchronous Controller bridge for Agent-owned instance lifecycle commands.

This module intentionally has no local-process fallback.  A lifecycle request is
accepted only when the instance is registered in the Controller database, is
assigned to an active Agent, and that Agent completes the command through the
Agent heartbeat/runtime-command protocol.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

DSM_ROOT = Path(os.environ.get("DSM_ROOT", Path(__file__).resolve().parents[1])).resolve()
DATABASE_DIR = DSM_ROOT / "database"
if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))

from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from runtime_backend import backend_from_environment

VALID_ACTIONS = {"start", "stop", "restart", "status"}
FINAL_STATES = {"completed", "failed"}
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_POLL_SECONDS = 0.5


def _instance_id_from_path(raw_path: str) -> str:
    if not raw_path:
        raise ValueError("instance path is required")
    root = (DSM_ROOT / "instances").resolve()
    candidate = Path(raw_path).expanduser().resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("instance path must be inside DSM instances root") from exc
    if len(relative.parts) != 3:
        raise ValueError("instance path must identify server, game and instance")
    return relative.parts[2]


def _registered_agent(repository: AgentInstanceRuntimeRepository, instance_id: str) -> str:
    ph = repository.dialect.placeholder
    with repository.session() as session:
        row = session.execute(
            f"SELECT agent_id FROM instances WHERE id={ph}",
            (instance_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Instance not found")
    agent_id = str(row["agent_id"] or "").strip()
    if not agent_id:
        raise ValueError("Instance has no Agent assignment")
    return agent_id


def execute(
    action: str,
    instance_path: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> dict[str, Any]:
    action = str(action or "").strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError("invalid instance action")

    instance_id = _instance_id_from_path(instance_path)
    backend = backend_from_environment()
    repository = AgentInstanceRuntimeRepository(backend)
    repository.initialize()
    agent_id = _registered_agent(repository, instance_id)

    command = repository.enqueue(
        agent_id=agent_id,
        instance_id=instance_id,
        action=action,
        requested_by=str(os.environ.get("DSM_USER") or "system"),
    )
    command_id = str(command["command_id"])
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))

    while True:
        snapshot = repository.snapshot(command_id)
        status = str(snapshot.get("status") or "").strip().lower()
        if status in FINAL_STATES:
            if status == "failed":
                raise RuntimeError(
                    str(snapshot.get("last_error") or "Agent failed instance command")
                )
            result = snapshot.get("result")
            agent_result = result if isinstance(result, dict) else {}
            payload = agent_result.get("result") if isinstance(agent_result.get("result"), dict) else {}
            return {
                "ok": True,
                "command_id": command_id,
                "agent_id": agent_id,
                "instance_id": instance_id,
                "action": action,
                "status": "completed",
                "observed_state": payload.get("observed_state"),
                "result": payload,
            }
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Agent did not complete instance command within {int(timeout_seconds)} seconds"
            )
        time.sleep(max(0.1, float(poll_seconds)))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(json.dumps({"error": "usage: instance_runtime_command.py ACTION INSTANCE_PATH"}), file=sys.stderr)
        return 2
    try:
        result = execute(argv[1], argv[2])
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
