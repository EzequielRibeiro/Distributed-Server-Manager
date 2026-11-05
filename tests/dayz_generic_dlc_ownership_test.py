"""Regression coverage for DayZ DLC content ownership on transactional staging."""
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
from server_update_agent import _ensure_dayz_dlc_ownership, ServerUpdateError


@pytest.fixture
def staging(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()
    for name in ("nasdara", "sakhal", "future_world"):
        addons = root / name / "addons"
        addons.mkdir(parents=True)
        (addons / ("ai_" + name + ".pbo")).write_bytes(b"pbo")
    workshop = root / "@community" / "addons"
    workshop.mkdir(parents=True)
    (workshop / "custom.pbo").write_bytes(b"custom")
    custom = root / "custom_mod" / "addons"
    custom.mkdir(parents=True)
    (custom / "custom.pbo").write_bytes(b"custom")
    (root / "custom_mod" / "mod.cpp").write_text("name=mod")
    (root / "addons").mkdir()
    (root / "addons" / "base.pbo").write_bytes(b"base")
    return root


def run_mocked(staging, game="dayz"):
    calls = []
    def chown(path, uid, gid, *, follow_symlinks):
        calls.append((Path(path), uid, gid, follow_symlinks))
    with mock.patch("pwd.getpwnam", return_value=types.SimpleNamespace(pw_uid=1234)), mock.patch("grp.getgrnam", return_value=types.SimpleNamespace(gr_gid=5678)), mock.patch("server_update_agent.os.chown", side_effect=chown):
        _ensure_dayz_dlc_ownership(staging, game)
    return calls


def test_detects_future_dlc_without_named_allowlist(staging):
    calls = run_mocked(staging)
    paths = {item[0] for item in calls}
    for name in ("nasdara", "sakhal", "future_world"):
        assert staging / name in paths
        assert staging / name / "addons" / ("ai_" + name + ".pbo") in paths
    assert all(uid == 1234 and gid == 5678 and follow is False for _, uid, gid, follow in calls)


def test_mods_and_base_game_are_untouched(staging):
    paths = {item[0] for item in run_mocked(staging)}
    assert staging / "@community" not in paths
    assert staging / "custom_mod" not in paths
    assert staging / "addons" not in paths


def test_other_games_unaffected(staging):
    assert run_mocked(staging, "palworld") == []


def test_no_dlc_is_noop(tmp_path):
    assert run_mocked(tmp_path) == []


def test_symlink_in_candidate_fails_before_chown(staging, tmp_path):
    (staging / "future_world" / "addons" / "escape").symlink_to(tmp_path)
    with mock.patch("pwd.getpwnam", return_value=types.SimpleNamespace(pw_uid=1234)), mock.patch("grp.getgrnam", return_value=types.SimpleNamespace(gr_gid=5678)), mock.patch("server_update_agent.os.chown") as chown:
        with pytest.raises(ServerUpdateError, match="symlink"):
            _ensure_dayz_dlc_ownership(staging, "dayz")
        chown.assert_not_called()


def test_chown_failure_fails_closed(staging):
    with mock.patch("pwd.getpwnam", return_value=types.SimpleNamespace(pw_uid=1234)), mock.patch("grp.getgrnam", return_value=types.SimpleNamespace(gr_gid=5678)), mock.patch("server_update_agent.os.chown", side_effect=PermissionError("denied")):
        with pytest.raises(ServerUpdateError, match="cannot assign DayZ DLC"):
            _ensure_dayz_dlc_ownership(staging, "dayz")
