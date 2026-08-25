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
        "arguments": ["-config=/var/lib/capivara-instances/aurora-dayz-002/config/serverDZ.cfg"],
        "environment": {"CAPIVARA_INSTANCE_ID": "aurora-dayz-002"},
    }
    spec.update(overrides)
    return spec


def test_working_directory_is_rendered_as_absolute_path_without_quotes():
    unit = render_unit(_spec())

    assert "WorkingDirectory=/var/lib/capivara-agent/game-data/dayz/serverfiles\n" in unit
    assert 'WorkingDirectory="/var/lib/capivara-agent/game-data/dayz/serverfiles"' not in unit
    assert 'ExecStart="/var/lib/capivara-agent/game-data/dayz/serverfiles/DayZServer"' in unit


def test_working_directory_rejects_relative_path():
    with pytest.raises(MaterializerError, match="absolute path"):
        render_unit(_spec(working_directory="relative/serverfiles"))


def test_working_directory_rejects_line_breaks():
    with pytest.raises(MaterializerError, match="invalid characters"):
        render_unit(_spec(working_directory="/var/lib/capivara-agent\nInjected=true"))


def test_instance_gets_isolated_writable_home_visible_through_passwd_path():
    unit = render_unit(_spec())

    assert "StateDirectory=capivara-instances/aurora-dayz-002\n" in unit
    assert "StateDirectoryMode=0700\n" in unit
    assert (
        "BindPaths=/var/lib/capivara-instances/aurora-dayz-002:"
        "/var/lib/capivara-agent/runtime-home\n"
        in unit
    )
    assert 'BindPaths="/var/lib/capivara-instances/aurora-dayz-002:' not in unit
    assert 'Environment="HOME=/var/lib/capivara-agent/runtime-home"' in unit
    assert 'Environment="XDG_DATA_HOME=/var/lib/capivara-agent/runtime-home/.local/share"' in unit
    assert 'Environment="XDG_CACHE_HOME=/var/lib/capivara-agent/runtime-home/.cache"' in unit
    assert 'Environment="XDG_CONFIG_HOME=/var/lib/capivara-agent/runtime-home/.config"' in unit
    assert "/nonexistent" not in unit


def test_instance_can_bind_private_persistence_over_shared_game_data_mountpoint():
    unit = render_unit(_spec(bind_paths=[{
        "source": "/var/lib/capivara-instances/aurora-dayz-002/storage_1",
        "target": "/var/lib/capivara-agent/game-data/dayz/serverfiles/mpmissions/dayzOffline.chernarusplus/storage_1",
    }]))
    assert (
        "BindPaths=/var/lib/capivara-instances/aurora-dayz-002/storage_1:"
        "/var/lib/capivara-agent/game-data/dayz/serverfiles/mpmissions/dayzOffline.chernarusplus/storage_1"
        in unit
    )
    assert 'BindPaths="/var/lib/capivara-instances/aurora-dayz-002/storage_1:' not in unit


def test_bind_paths_reject_unsupported_pair_characters():
    with pytest.raises(MaterializerError, match="unsupported characters"):
        render_unit(_spec(bind_paths=[{
            "source": "/var/lib/capivara-instances/aurora-dayz-002/storage 1",
            "target": "/var/lib/capivara-agent/game-data/dayz/storage_1",
        }]))


def test_instance_state_directory_rejects_path_injection():
    with pytest.raises(MaterializerError, match="instance state directory"):
        render_unit(_spec(instance_id="../../escape"))
