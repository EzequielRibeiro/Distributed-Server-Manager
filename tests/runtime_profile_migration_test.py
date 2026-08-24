from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import game_runtime
import instance_runtime


def _legacy_dayz(tmp_path: Path) -> dict:
    install = tmp_path / "serverfiles"
    install.mkdir()
    return {
        "schema_version": 1,
        "kind": "CapivaraInstanceRuntimeSpec",
        "instance_id": "aurora-dayz-002",
        "agent_id": "agent-test",
        "game_id": "dayz",
        "environment_id": "dayz.stable",
        "runtime_id": "dayz.stable",
        "adapter": "systemd",
        "working_directory": str(install),
        "path": str(install),
        "executable": str(install / "DayZServer"),
        "arguments": ["-config=serverDZ.cfg", "-mod=@CF"],
        "environment": {},
        "user": "capivara-instance",
        "desired_state": "running",
        "observed_state": "stopped",
        "profile": "dayz",
        "profile_version": 1,
        "ports": {
            "game": {"port": 24010, "protocol": "udp"},
            "game_aux": {"port": 24012, "protocol": "udp"},
        },
        "writable_directories": [],
        "bind_paths": [],
    }


def test_legacy_dayz_profile_rebuilds_private_mutable_state(tmp_path, monkeypatch):
    monkeypatch.setattr(instance_runtime, "STATE_DIR", tmp_path / "state")
    legacy = _legacy_dayz(tmp_path)

    migrated, changed = game_runtime.migrate_runtime_spec({"agent_id": "agent-test"}, legacy)

    assert changed is True
    assert migrated["profile"] == "dayz"
    assert migrated["profile_version"] == 3
    assert migrated["profile_migrated_from_version"] == 1
    assert migrated["desired_state"] == "running"
    assert migrated["ports"]["game"]["port"] == 24010
    assert migrated["ports"]["steam_query"]["port"] == 24012

    state_root = "/var/lib/capivara-instances/aurora-dayz-002"
    assert migrated["instance_state_root"] == state_root
    assert migrated["config_path"] == f"{state_root}/config/serverDZ.cfg"
    assert f"{state_root}/profiles" in migrated["writable_directories"]
    assert f"{state_root}/storage_1" in migrated["writable_directories"]
    assert migrated["bind_paths"] == [{
        "source": f"{state_root}/storage_1",
        "target": str(Path(legacy["working_directory"]) / "mpmissions" / "dayzOffline.chernarusplus" / "storage_1"),
    }]

    assert f"-config={state_root}/config/serverDZ.cfg" in migrated["arguments"]
    assert "-port=24010" in migrated["arguments"]
    assert f"-profiles={state_root}/profiles" in migrated["arguments"]
    assert "-mod=@CF" in migrated["arguments"]
    assert "-config=serverDZ.cfg" not in migrated["arguments"]

    assert migrated["catalog_network_properties"] == [{
        "path": "serverDZ.cfg",
        "key": "steamQueryPort",
        "value": "{{PORT_STEAM_QUERY}}",
        "syntax": "semicolon",
    }]
    assert migrated["catalog_variables"]["PORT_STEAM_QUERY"] == "24012"


def test_current_profile_is_not_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(instance_runtime, "STATE_DIR", tmp_path / "state")
    legacy = _legacy_dayz(tmp_path)
    migrated, _ = game_runtime.migrate_runtime_spec({"agent_id": "agent-test"}, legacy)

    current, changed = game_runtime.migrate_runtime_spec({"agent_id": "agent-test"}, migrated)

    assert changed is False
    assert current is migrated


def test_profile_downgrade_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(instance_runtime, "STATE_DIR", tmp_path / "state")
    record = _legacy_dayz(tmp_path)
    record["profile_version"] = 99

    with pytest.raises(RuntimeError, match="downgrade refused"):
        game_runtime.migrate_runtime_spec({"agent_id": "agent-test"}, record)
