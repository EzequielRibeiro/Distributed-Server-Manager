"""Fail-closed DayZ maintenance rollback tests against disposable paths."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


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
        try:
            maintenance._prepare_locked(selection, target, lambda _: (_ for _ in ()).throw(
                RuntimeError("staging validation failed")) if stage_failure else None)
        except Exception as caught:
            return mocks, caught
        raise AssertionError("maintenance failed to reject invalid transaction")



class DayZMaintenanceRollbackFailureTests(unittest.TestCase):
    def run_scenario(self, **kwargs):
        with TemporaryDirectory() as temp:
            return scenario(Path(temp), **kwargs)

    def test_rollback_false_preserves_evidence(self):
        mocks, err = self.run_scenario(outcome=False)
        self.assertIsInstance(err, maintenance.MaintenanceGameUpdateError)
        self.assertIn("rollback tree is unavailable", str(err))
        mocks["rollback"].assert_called_once()
        mocks["restore_files"].assert_not_called()
        mocks["cleanup_staging"].assert_not_called()
        mocks["create_backup"].assert_called_once()

    def test_rollback_exception_preserves_evidence(self):
        mocks, err = self.run_scenario(failure=OSError("rename denied"))
        self.assertIsInstance(err, maintenance.MaintenanceGameUpdateError)
        self.assertIn("rollback failed", str(err))
        mocks["restore_files"].assert_not_called()
        mocks["cleanup_staging"].assert_not_called()

    def test_successful_rollback_restores_metadata_then_cleans(self):
        mocks, err = self.run_scenario(outcome=True)
        self.assertIsInstance(err, RuntimeError)
        self.assertIn("post-activation", str(err))
        mocks["rollback"].assert_called_once()
        mocks["restore_files"].assert_called_once()
        mocks["cleanup_staging"].assert_called_once()

    def test_failed_staging_does_not_attempt_rollback(self):
        mocks, err = self.run_scenario(stage_failure=True)
        self.assertIn("staging validation failed", str(err))
        mocks["rollback"].assert_not_called()
        mocks["cleanup_staging"].assert_called_once()

    def test_backup_opt_out_cannot_skip_dayz_backup(self):
        mocks, err = self.run_scenario(backup_failure=True)
        self.assertIn("backup failed", str(err))
        mocks["create_backup"].assert_called_once()
        mocks["activate"].assert_not_called()
        mocks["rollback"].assert_not_called()
        mocks["cleanup_staging"].assert_called_once()


if __name__ == "__main__":
    unittest.main()
