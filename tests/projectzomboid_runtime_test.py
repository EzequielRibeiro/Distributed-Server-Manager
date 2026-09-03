#!/usr/bin/env python3
"""Deterministic regression for Project Zomboid runtime/bootstrap policy."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
sys.path.insert(0, str(RUNTIME))

from materializers.systemd import render_unit
from profiles.projectzomboid import ProjectZomboidRuntimeProfile
from runtime_spec import RuntimeSpecError, validate_runtime_spec


def _spec():
    profile = ProjectZomboidRuntimeProfile()
    return profile.build_runtime_spec(
        {
            "instance_id": "pz-test-001",
            "agent_id": "agent-test",
            "environment_id": "projectzomboid.stable",
            "runtime_id": "projectzomboid.stable",
            "desired_state": "running",
        },
        {
            "install_path": "/var/lib/capivara-agent/game-data/projectzomboid",
            "ports": {"game": {"port": 16261, "protocol": "udp"}},
            "instance_state_root": "/var/lib/capivara-instances/pz-test-001",
        },
    )


def main() -> int:
    spec = validate_runtime_spec(_spec(), expected_agent_id="agent-test")
    assert spec["game_id"] == "projectzomboid"
    assert spec["arguments"] == ["-servername", "servertest", "-port", "16261"]
    assert len(spec["pre_start"]) == 1
    pre = spec["pre_start"][0]
    assert pre["executable"] == "/usr/bin/python3"
    assert pre["arguments"][0] == "/opt/capivara-agent/runtime/projectzomboid_bootstrap.py"
    unit = render_unit(spec)
    assert "ExecStartPre=" in unit
    assert "projectzomboid_bootstrap.py" in unit
    assert "adminpassword" not in unit.lower()
    assert "password" not in unit.lower()

    broken = dict(spec)
    broken["pre_start"] = [{"executable": "relative", "arguments": []}]
    try:
        validate_runtime_spec(broken, expected_agent_id="agent-test")
    except RuntimeSpecError:
        pass
    else:
        raise AssertionError("relative pre-start executable must be rejected")

    text = (RUNTIME / "projectzomboid_bootstrap.py").read_text(encoding="utf-8")
    assert "secrets.token_urlsafe" in text
    assert "stdin_payload" in text
    assert "-adminpassword" not in text
    assert "stdout=subprocess.DEVNULL" in text
    assert "stderr=subprocess.DEVNULL" in text
    print("Project Zomboid runtime/bootstrap contract: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
