#!/usr/bin/env python3
"""DayZ customer file browser: bounded, instance-private read repair."""
from __future__ import annotations

import os
import pwd
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "agents/linux/runtime", ROOT / "agents/linux/privileged"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import instance_files_client
import materialize_instance
import privileged_materialization


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _setup(tmp_path: Path):
    pool = tmp_path / "pool"
    root = pool / "cli-000001-dayz-002"
    mission = root / "mpmissions" / "hardcore.namalsk"
    mission.mkdir(parents=True)
    mission.chmod(0o700)
    mission.parent.chmod(0o700)
    secret = root / ".dsm"
    secret.mkdir()
    secret.chmod(0o700)
    root.chmod(0o710)
    work = tmp_path / "serverfiles"
    work.mkdir()
    owner = pwd.getpwuid(os.geteuid())
    spec = {
        "instance_id": root.name, "agent_id": "agent-vps",
        "game_id": "dayz", "user": owner.pw_name,
        "instance_state_root": str(root), "files_root": str(root),
        "working_directory": str(work),
    }
    return pool, root, mission, secret, spec


def test_repair_only_requested_mission_access_not_private_control(tmp_path):
    pool, root, mission, secret, spec = _setup(tmp_path)
    owner = pwd.getpwuid(os.geteuid())
    group = SimpleNamespace(gr_gid=os.getegid())
    with mock.patch.object(materialize_instance, "_instance_storage_root", return_value=pool), \
         mock.patch.object(materialize_instance, "_validate_runtime_user", return_value=owner), \
         mock.patch.object(materialize_instance.pwd, "getpwnam", return_value=owner), \
         mock.patch.object(materialize_instance.grp, "getgrnam", return_value=group):
        result = materialize_instance._prepare_dayz_customer_read_access(
            spec, {"agent_id": "agent-vps"}, "mpmissions/hardcore.namalsk"
        )
        again = materialize_instance._prepare_dayz_customer_read_access(
            spec, {"agent_id": "agent-vps"}, "mpmissions/hardcore.namalsk"
        )
    assert result["changed"] is True
    assert again["changed"] is False
    assert _mode(root) == 0o710
    assert _mode(mission.parent) == 0o750
    assert _mode(mission) == 0o750
    assert _mode(secret) == 0o700


@pytest.mark.parametrize("requested", [
    ".", ".dsm", ".dsm/secrets.json", "content/workshop", "../other",
    "mpmissions/../.dsm", "/etc/passwd",
])
def test_denied_paths_never_repair(tmp_path, requested):
    pool, root, mission, secret, spec = _setup(tmp_path)
    owner = pwd.getpwuid(os.geteuid())
    with mock.patch.object(materialize_instance, "_instance_storage_root", return_value=pool), \
         mock.patch.object(materialize_instance, "_validate_runtime_user", return_value=owner):
        with pytest.raises(PermissionError):
            materialize_instance._prepare_dayz_customer_read_access(
                spec, {"agent_id": "agent-vps"}, requested
            )
    assert _mode(secret) == 0o700


def test_symlink_mission_refused_without_touching_target(tmp_path):
    pool, root, mission, secret, spec = _setup(tmp_path)
    mission.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    mission.symlink_to(outside, target_is_directory=True)
    owner = pwd.getpwuid(os.geteuid())
    group = SimpleNamespace(gr_gid=os.getegid())
    with mock.patch.object(materialize_instance, "_instance_storage_root", return_value=pool), \
         mock.patch.object(materialize_instance, "_validate_runtime_user", return_value=owner), \
         mock.patch.object(materialize_instance.pwd, "getpwnam", return_value=owner), \
         mock.patch.object(materialize_instance.grp, "getgrnam", return_value=group):
        with pytest.raises(PermissionError):
            materialize_instance._prepare_dayz_customer_read_access(
                spec, {"agent_id": "agent-vps"}, "mpmissions/hardcore.namalsk"
            )
    assert _mode(outside) == 0o755


def test_agent_retries_once_on_denied_mission_listing(tmp_path):
    pool, root, mission, secret, spec = _setup(tmp_path)
    expected = {"path": "mpmissions/hardcore.namalsk", "entries": []}
    command = {
        "instance_id": root.name, "action": "list",
        "path": "mpmissions/hardcore.namalsk",
    }
    with mock.patch.object(instance_files_client, "_owned", return_value=spec), \
         mock.patch.object(instance_files_client, "_list",
                           side_effect=[PermissionError("denied"), expected]) as listing, \
         mock.patch.object(privileged_materialization, "prepare_dayz_customer_read_access",
                           return_value={"changed": True}) as prepare:
        result = instance_files_client.execute({"agent_id": "agent-vps"}, command)
    assert result == expected
    assert listing.call_count == 2
    prepare.assert_called_once_with(
        {"agent_id": "agent-vps"}, spec, "mpmissions/hardcore.namalsk"
    )


def test_agent_denied_private_path_never_invokes_privileged_repair(tmp_path):
    pool, root, mission, secret, spec = _setup(tmp_path)
    command = {"instance_id": root.name, "action": "list", "path": ".dsm"}
    with mock.patch.object(instance_files_client, "_owned", return_value=spec), \
         mock.patch.object(privileged_materialization, "prepare_dayz_customer_read_access") as prepare:
        with pytest.raises(PermissionError):
            instance_files_client.execute({"agent_id": "agent-vps"}, command)
    prepare.assert_not_called()
