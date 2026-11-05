"""Fail-closed DayZ maintenance rollback tests against disposable paths."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from agents.linux.runtime import maintenance_game_update as maintenance


def scenario(root: Path, *, outcome=False, failure=None, stage_failure=False, backup_failure=False):
    target = root / "serverfiles"
    stage = root / "staging"
    old = root / "previous"
    for path in (target, stage, old):
        path.mkdir()
    record = {"agent_id": "agent-one", "game_id": "dayz"}
    selection = {"game": "dayz"}
    def detect(_selection, path, _steamcmd=None, **options):
        if path == target and not options.get("force_refresh"):
            return {"state": "update_available"}
        if path == stage:
            return {"state": "up_to_date"}
        raise RuntimeError("post-activation version detection failed")
    patches = {
        "_context": (("instance-one", record, {"backup_before_update": False}), {}),
        "_local_agent_config": ({}, {}),
        "_affected": (["instance-one"], {}),
        "_all_stopped": (None, {}),
        "reject_prepared_dayz_transaction": (None, {}),
        "_ensure_staging_space": (None, {}),
        "_provider_metadata_snapshot": ({}, {}),
        "prepare_staging": (stage, {}),
        "detect_update": (None, {"side_effect": detect}),
        "activate": (old, {}),
        "rollback": (outcome, {"side_effect": failure} if failure else {}),
        "restore_files": (None, {}),
        "cleanup_staging": (None, {}),
        "create_backup": ({"backup_id": "backup-ok"}, {"side_effect": RuntimeError("backup failed")} if backup_failure else {}),
    }
    with ExitStack() as stack:
        mocks = {}
        for name, (value, kw) in patches.items():
            settings = kw if kw else {"return_value": value}
            mocks[name] = stack.enter_context(patch.object(maintenance, name, **settings))
        with pytest.raises(Exception) as caught:
            maintenance._prepare_locked(selection, target, lambda _: (_ for _ in ()).throw(
                RuntimeError("staging validation failed")) if stage_failure else None)
        return mocks, caught.value


def test_rollback_false_preserves_evidence(tmp_path):
    mocks, err = scenario(tmp_path, outcome=False)
    assert isinstance(err, maintenance.MaintenanceGameUpdateError)
    assert "rollback tree is unavailable" in str(err)
    mocks["rollback"].assert_called_once()
    mocks["restore_files"].assert_not_called()
    mocks["cleanup_staging"].assert_not_called()
    mocks["create_backup"].assert_called_once()


def test_rollback_exception_preserves_evidence(tmp_path):
    mocks, err = scenario(tmp_path, failure=OSError("rename denied"))
    assert isinstance(err, maintenance.MaintenanceGameUpdateError)
    assert "rollback failed" in str(err)
    mocks["restore_files"].assert_not_called()
    mocks["cleanup_staging"].assert_not_called()


def test_successful_rollback_restores_metadata_then_cleans(tmp_path):
    mocks, err = scenario(tmp_path, outcome=True)
    assert isinstance(err, RuntimeError)
    assert "post-activation" in str(err)
    mocks["rollback"].assert_called_once()
    mocks["restore_files"].assert_called_once()
    mocks["cleanup_staging"].assert_called_once()


def test_failed_staging_does_not_attempt_rollback(tmp_path):
    mocks, err = scenario(tmp_path, stage_failure=True)
    assert "staging validation failed" in str(err)
    mocks["rollback"].assert_not_called()
    mocks["cleanup_staging"].assert_called_once()


def test_backup_opt_out_cannot_skip_dayz_backup(tmp_path):
    mocks, err = scenario(tmp_path, backup_failure=True)
    assert "backup failed" in str(err)
    mocks["create_backup"].assert_called_once()
    mocks["activate"].assert_not_called()
    mocks["rollback"].assert_not_called()
    mocks["cleanup_staging"].assert_called_once()
