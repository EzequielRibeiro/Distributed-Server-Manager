"""DayZ Agent-managed installation root ACL regression tests."""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
MATERIALIZER = ROOT / "agents/linux/privileged/materialize_instance.py"


def load():
    spec = importlib.util.spec_from_file_location("dayz_runtime_root_acl_under_test", MATERIALIZER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def setup(tmp_path):
    module = load()
    module.STATE_DIR = tmp_path / "state"
    working = module.STATE_DIR / "game-data" / "dayz" / "serverfiles"
    working.mkdir(parents=True)
    (working / "dta").mkdir()
    (working / "dta" / "scripts.pbo").write_bytes(b"pbo")
    return module, working


def _identity_patches(module, working):
    owner = types.SimpleNamespace(pw_uid=working.stat().st_uid)
    group = types.SimpleNamespace(gr_gid=working.stat().st_gid)
    return (
        mock.patch.object(module.pwd, "getpwnam", return_value=owner),
        mock.patch.object(module.grp, "getgrnam", return_value=group),
        mock.patch.object(module, "_validate_runtime_user", return_value=owner),
    )


def test_managed_dayz_grants_only_root_acl(setup):
    module, working = setup
    owner, group, runtime = _identity_patches(module, working)
    with owner, group, runtime, mock.patch.object(
        module.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stderr="")
    ) as run:
        assert module._ensure_dayz_runtime_root_acl({
            "game_id": "dayz",
            "user": "capivara-instance",
            "working_directory": str(working),
        })
    run.assert_called_once_with(
        ["setfacl", "-m", "u:capivara-instance:rwx", str(working)],
        capture_output=True, text=True, check=False, timeout=30,
    )


def test_other_games_and_unmanaged_locations_unchanged(setup, tmp_path):
    module, working = setup
    unmanaged = tmp_path / "outside"
    unmanaged.mkdir()
    with mock.patch.object(module.subprocess, "run") as run:
        assert not module._ensure_dayz_runtime_root_acl(
            {"game_id": "minecraft", "working_directory": str(working)})
        assert not module._ensure_dayz_runtime_root_acl(
            {"game_id": "dayz", "working_directory": str(unmanaged)})
        assert not module._ensure_dayz_runtime_root_acl(
            {"game_id": "dayz", "working_directory": str(working), "user": "untrusted"})
        run.assert_not_called()


def test_reject_symlink_and_nested_install(setup):
    module, working = setup
    link = working.parent / "linked"
    link.symlink_to(working, target_is_directory=True)
    with pytest.raises(RuntimeError, match="non-symlink"):
        module._ensure_dayz_runtime_root_acl({"game_id": "dayz", "working_directory": str(link)})
    nested = working / "dta"
    with pytest.raises(RuntimeError, match="expected game-data root"):
        module._ensure_dayz_runtime_root_acl({"game_id": "dayz", "working_directory": str(nested)})


def test_untrusted_ownership_rejected(setup):
    module, working = setup
    with mock.patch.object(module.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=working.stat().st_uid + 1)), \
         mock.patch.object(module.grp, "getgrnam", return_value=types.SimpleNamespace(gr_gid=working.stat().st_gid)), \
         mock.patch.object(module.subprocess, "run") as run:
        with pytest.raises(RuntimeError, match="not owned"):
            module._ensure_dayz_runtime_root_acl({"game_id": "dayz", "working_directory": str(working)})
        run.assert_not_called()


def test_missing_or_failed_acl_tool_fails_closed(setup):
    module, working = setup
    owner, group, runtime = _identity_patches(module, working)
    with owner, group, runtime:
        with mock.patch.object(module.subprocess, "run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="install the acl package"):
                module._ensure_dayz_runtime_root_acl({"game_id": "dayz", "working_directory": str(working)})
        with mock.patch.object(module.subprocess, "run", return_value=types.SimpleNamespace(returncode=1, stderr="denied")):
            with pytest.raises(RuntimeError, match="denied"):
                module._ensure_dayz_runtime_root_acl({"game_id": "dayz", "working_directory": str(working)})


def test_installer_declares_acl_on_all_supported_package_managers():
    text = (ROOT / "agents/linux/installer/install-agent.sh").read_text()
    assert 'local -a packages=(ca-certificates acl)' in text
    for manager in ("apt-get", "dnf", "yum", "zypper"):
        assert f"command -v {manager}" in text
    assert "id setfacl; do" in text
