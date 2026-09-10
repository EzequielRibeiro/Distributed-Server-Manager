#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from configuration_repository import ConfigurationRepository


def process_hybrid_configuration_cycle(
    backend,
    root: Path,
    agent_id: str,
) -> dict[str, Any]:
    root = Path(root)
    state_root = root / "runtime" / "hybrid-agent-state"
    config_path = state_root / "agent.json"
    runtime_dir = root / "agents" / "linux" / "runtime"

    old_state = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
    old_config = os.environ.get("CAPIVARA_AGENT_CONFIG")

    if str(runtime_dir) not in sys.path:
        sys.path.insert(0, str(runtime_dir))

    try:
        os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(state_root)
        os.environ["CAPIVARA_AGENT_CONFIG"] = str(config_path)

        from configuration_client import (
            apply_configuration_commands,
            configuration_state,
        )

        repository = ConfigurationRepository(backend)
        repository.initialize()

        # Primeiro registra o estado já aplicado localmente.
        reports = configuration_state()
        accepted = (
            repository.record_agent_state(agent_id, reports)
            if reports
            else 0
        )

        # Depois resolve somente configurações ainda pendentes.
        commands = repository.desired_for_agent(agent_id)
        applied = apply_configuration_commands(commands) if commands else reports

        # Registra imediatamente o resultado para não esperar outro ciclo.
        reported = (
            repository.record_agent_state(agent_id, applied)
            if commands and applied
            else 0
        )

        return {
            "status": "active",
            "commands": len(commands),
            "reports_accepted": accepted + reported,
            "state": applied,
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


__all__ = ["process_hybrid_configuration_cycle"]
