from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from materializers.base import MaterializerError
from materializers.systemd import render_unit


def _spec(**overrides):
    spec = {
        "instance_id": "aurora-dayz-002",
        "agent_id": "agent-01",
        "runtime_id": "dayz.stable",
        "user": "capivara-instance",
        "working_directory": "/var/lib/capivara-agent/game-data/dayz/serverfiles",
        "executable": "/var/lib/capivara-agent/game-data/dayz/serverfiles/DayZServer",
        "arguments": ["-config=serverDZ.cfg"],
        "environment": {"CAPIVARA_INSTANCE_ID": "aurora-dayz-002"},
    }
    spec.update(overrides)
    return spec


def test_working_directory_is_rendered_as_absolute_path_without_quotes():
    unit = render_unit(_spec())

    assert (
        "WorkingDirectory=/var/lib/capivara-agent/game-data/dayz/serverfiles\n"
        in unit
    )
    assert 'WorkingDirectory="/var/lib/capivara-agent/game-data/dayz/serverfiles"' not in unit
    assert (
        'ExecStart="/var/lib/capivara-agent/game-data/dayz/serverfiles/DayZServer" '
        '"-config=serverDZ.cfg"'
        in unit
    )


def test_working_directory_rejects_relative_path():
    with pytest.raises(MaterializerError, match="absolute path"):
        render_unit(_spec(working_directory="relative/serverfiles"))
