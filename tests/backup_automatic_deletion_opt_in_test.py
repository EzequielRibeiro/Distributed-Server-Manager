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


    def test_queued_retention_delete_is_not_sent_without_opt_in(self):
        repository = object.__new__(BackupRepository)
        pending = [
            {"command_id": "old-command", "action": "delete", "reason": "age_retention", "instance_id": "instance", "backup_id": "old"},
            {"command_id": "legacy-command", "action": "delete", "reason": None, "instance_id": "instance", "backup_id": "legacy"},
            {"command_id": "manual-command", "action": "delete", "reason": "manual", "instance_id": "instance", "backup_id": "manual"},
            {"command_id": "customer-command", "action": "delete", "reason": "customer", "instance_id": "instance", "backup_id": "customer"},
        ]
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(repository, "schedule_due", return_value=[]),
            patch.object(repository, "list_jobs", return_value=pending),
            patch.object(repository, "get_policy", return_value={}),
            patch.object(repository, "_workspace_schedule", return_value=None),
            patch.object(repository, "_age_retention_days", return_value=None),
        ):
            commands = repository.commands_for_agent("agent")
        self.assertEqual(len(commands), 2)
        self.assertEqual(
            {item["backup_id"] for item in commands}, {"manual", "customer"}
        )
        self.assertTrue(all(item["action"] == "delete" for item in commands))

    def test_customer_deletion_pending_before_upgrade_is_forwarded_with_original_id(self):
        repository = object.__new__(BackupRepository)
        job = {
            "command_id": "historic-pending-delete",
            "action": "delete",
            "reason": "customer",
            "instance_id": "cli-000001-dayz-001",
            "backup_id": "backup-old",
            "requested_by": "customer",
        }
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(repository, "schedule_due", return_value=[]),
            patch.object(repository, "list_jobs", return_value=[job]),
            patch.object(repository, "get_policy", return_value={}),
            patch.object(repository, "_workspace_schedule", return_value=None),
            patch.object(repository, "_age_retention_days", return_value=None),
        ):
            commands = repository.commands_for_agent("hybrid-agent")
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["command_id"], "historic-pending-delete")
        self.assertEqual(commands[0]["reason"], "customer")
        self.assertEqual(commands[0]["backup_id"], "backup-old")



if __name__ == "__main__":
    unittest.main()
