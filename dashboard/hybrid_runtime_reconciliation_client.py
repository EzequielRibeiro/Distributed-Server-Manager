#!/usr/bin/env python3
"""Run Agent runtime reconciliation for instances hosted by the local Hybrid Agent."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


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


def process_hybrid_runtime_reconciliation_cycle(
    root: Path,
    agent_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    _runtime_import(root)

    state_dir = root / "runtime" / "hybrid-agent-state"
    config_path = state_dir / "agent.json"

    old_state = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
    old_config = os.environ.get("CAPIVARA_AGENT_CONFIG")
    old_materializer = os.environ.get("CAPIVARA_MATERIALIZER_UNIT_TEMPLATE")

    os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(state_dir)
    os.environ["CAPIVARA_AGENT_CONFIG"] = str(config_path)
    os.environ["CAPIVARA_MATERIALIZER_UNIT_TEMPLATE"] = (
        "dsm-hybrid-agent-materialize@{instance_id}.service"
    )

    try:
        import runtime_reconciler

        config = _agent_config(root, agent_id)
        results = runtime_reconciler.reconcile_all(config, force=force)

        return {
            "status": "completed",
            "instances": len(results),
            "results": results,
        }
    finally:
        if old_state is None:
            os.environ.pop("CAPIVARA_AGENT_STATE_DIR", None)
        else:
            os.environ["CAPIVARA_AGENT_STATE_DIR"] = old_state

        if old_config is None:
            os.environ.pop("CAPIVARA_AGENT_CONFIG", None)
        else:
            os.environ["CAPIVARA_AGENT_CONFIG"] = old_config


__all__ = ["process_hybrid_runtime_reconciliation_cycle"]
