"""Automatic backup deletion must require explicit operator opt-in."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "database"))
from database.backup_repository import BackupRepository


class AutomaticDeletionOptInTest(unittest.TestCase):
    def test_default_disables_scheduled_deletion_before_any_db_access(self):
        repository = object.__new__(BackupRepository)
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(repository, "_workspace_schedule") as schedule,
            patch.object(repository, "list_jobs") as jobs,
        ):
            self.assertEqual(repository._single_operational_cleanup("instance", "backup"), [])
            schedule.assert_not_called()
            jobs.assert_not_called()

    def test_invalid_opt_in_does_not_enable_deletion(self):
        repository = object.__new__(BackupRepository)
        with (
            patch.dict(os.environ, {"DSM_BACKUP_ALLOW_AUTOMATIC_DELETION": "true"}),
            patch.object(repository, "_workspace_schedule") as schedule,
        ):
            self.assertEqual(repository._single_operational_cleanup("instance", "backup"), [])
            schedule.assert_not_called()


    def test_explicit_opt_in_still_respects_workspace_policy(self):
        repository = object.__new__(BackupRepository)
        with (
            patch.dict(os.environ, {"DSM_BACKUP_ALLOW_AUTOMATIC_DELETION": "1"}),
            patch.object(repository, "_workspace_schedule", return_value={"keep_single_operational": False}) as schedule,
            patch.object(repository, "list_jobs") as jobs,
        ):
            self.assertEqual(repository._single_operational_cleanup("instance", "backup"), [])
            schedule.assert_called_once_with("instance")
            jobs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
