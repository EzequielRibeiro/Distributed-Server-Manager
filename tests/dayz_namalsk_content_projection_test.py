#!/usr/bin/env python3
"""Namalsk dependencies survive enabling the rest of DayZ UCP content.

Uses disposable paths; never interacts with a live DayZ process or Agent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "agents/linux/runtime", ROOT / "agents/common"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import content_activation_dayz
import content_activation_projection
import content_activation_runtime
import dayz_community_missions


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [
        (False, ("2289456201", "2289461232")),
        (True, ("2289456201", "2289461232", "1559212036", "1828439124")),
    ],
)
def test_active_namalsk_mission_keeps_deps_when_cf_vpp_enabled(tmp_path, monkeypatch, enabled, expected):
    instance_id = "cli-test-dayz-namalsk"
    state_root = tmp_path / "instance"
    working = tmp_path / "serverfiles"
    working.mkdir()
    managed = state_root / "content" / "workshop"
    managed.mkdir(parents=True)
    ids = ("2289456201", "2289461232", "1559212036", "1828439124")
    for wid in ids:
        (managed / f"steam-workshop:{wid}").mkdir()
    map_folder = managed / "community-map"
    map_folder.mkdir()
    (map_folder / "hardcore.namalsk").mkdir()

    config = state_root / "config" / "serverDZ.cfg"
    config.parent.mkdir()
    config.write_text('class Missions { class DayZ { template="hardcore.namalsk"; }; };')

    states = [{
        "content_id": "community-map-namalsk",
        "instance_id": instance_id,
        "game_id": "dayz",
        "content_type": "map",
        "status": "applied",
        "desired_state": "installed",
        "security_state": "clean",
        "installed_version": "1",
        "managed_path": str(map_folder),
        "activation_state": "disabled",
        "dependencies": ["steam-workshop:2289456201", "steam-workshop:2289461232"],
        "community_map": {"mission_path": "hardcore.namalsk"},
    }]
    for order, wid in enumerate(ids, 10):
        states.append({
            "content_id": f"steam-workshop:{wid}",
            "instance_id": instance_id,
            "game_id": "dayz",
            "content_type": "mod",
            "status": "applied",
            "desired_state": "installed",
            "security_state": "clean",
            "installed_version": "1",
            "managed_path": str(managed / f"steam-workshop:{wid}"),
            "package_id": f"221100:{wid}",
            "activation_state": "disabled" if wid in {"2289456201", "2289461232"} else "enabled",
            "activation_order": order,
            "activation": {"adapter": "dayz", "mode": "mod"},
            "dependencies": ["steam-workshop:1559212036"] if wid == "1828439124" else [],
        })
    monkeypatch.setattr(content_activation_projection, "_load_instance_states", lambda iid: states)
    fake_missions = lambda root, mission_path=None: [{"id": "hardcore.namalsk", "relative_path": "hardcore.namalsk"}]
    monkeypatch.setattr(dayz_community_missions, "discover_community_missions", fake_missions)
    monkeypatch.setattr(content_activation_dayz, "discover_community_missions", fake_missions)

    spec = {
        "instance_id": instance_id,
        "game_id": "dayz",
        "instance_state_root": str(state_root),
        "working_directory": str(working),
        "config_path": str(config),
        "arguments": ["-config=serverDZ.cfg"],
        "dayz_content_enabled": enabled,
    }
    prepared, snapshot = content_activation_projection.runtime_projection_inputs(
        instance_id, spec,
    )
    assert set(prepared["dayz_required_content_ids"]) == {
        "steam-workshop:2289456201",
        "steam-workshop:2289461232",
    }
    result = content_activation_runtime.project_runtime_spec(prepared, snapshot)
    mod_flags = [arg for arg in result["arguments"] if arg.startswith("-mod=")]
    assert len(mod_flags) == 1
    projected = [value.rsplit("-", 1)[-1] for value in mod_flags[0][5:].split(";")]
    assert tuple(projected) == expected
    assert result["dayz_content_enabled"] is enabled
