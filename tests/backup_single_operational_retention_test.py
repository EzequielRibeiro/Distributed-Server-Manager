"""Single-operational backup retention must wait for committed replacement."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))
from backup_repository import BackupRepository


class SingleOperationalRetentionTest(unittest.TestCase):
    def setUp(self):
        self.repo = object.__new__(BackupRepository)
        self.repo._workspace_schedule = Mock(return_value={"keep_single_operational": True})
        self.repo.request = Mock(side_effect=lambda *args, **kwargs: {"backup_id": kwargs.get("backup_id")})

    def _jobs(self, latest="new", deletion=None):
        result = [
            {"action": "create", "status": "completed", "backup_id": latest,
             "sha256": "a" * 64, "artifact_path": "/backups/new.tar.gz"},
            {"action": "create", "status": "completed", "backup_id": "old",
             "sha256": "b" * 64, "artifact_path": "/backups/old.tar.gz"},
        ]
        if deletion:
            result.append({"action": "delete", "status": deletion, "backup_id": "old"})
        return result

    def test_queues_only_old_backup_after_replacement_is_committed(self):
        self.repo.list_jobs = Mock(return_value=self._jobs())
        result = self.repo._single_operational_cleanup("instance", "new")
        self.assertEqual(["old"], [j["backup_id"] for j in result])
        self.repo.request.assert_called_once_with("instance", action="delete", backup_id="old",
                                                 reason="operational_retention", requested_by="scheduler")

    def test_does_not_cleanup_when_newer_backup_exists(self):
        self.repo.list_jobs = Mock(return_value=self._jobs())
        self.assertEqual([], self.repo._single_operational_cleanup("instance", "old"))
        self.repo.request.assert_not_called()

    def test_does_not_duplicate_pending_or_completed_deletions(self):
        for status in ("pending", "running", "completed"):
            with self.subTest(status=status):
                self.repo.request.reset_mock()
                self.repo.list_jobs = Mock(return_value=self._jobs(deletion=status))
                self.assertEqual([], self.repo._single_operational_cleanup("instance", "new"))
                self.repo.request.assert_not_called()

    def test_disabled_or_missing_policy_never_prunes(self):
        for setting in (None, {"keep_single_operational": False}):
            with self.subTest(setting=setting):
                self.repo._workspace_schedule.return_value = setting
                self.repo.request.reset_mock()
                self.assertEqual([], self.repo._single_operational_cleanup("instance", "new"))
                self.repo.request.assert_not_called()

    def test_unverified_create_never_triggers_deletion(self):
        jobs = self._jobs()
        jobs[0]["sha256"] = None
        self.repo.list_jobs = Mock(return_value=jobs)
        self.assertEqual([], self.repo._single_operational_cleanup("instance", "new"))
        self.repo.request.assert_not_called()

    def test_14_day_policy_retains_all_current_and_last_valid(self):
        now = datetime.now(timezone.utc)
        jobs = [
            {"action": "create", "status": "completed", "backup_id": "new",
             "sha256": "a" * 64, "artifact_path": "/backups/new.tar.gz",
             "completed_at": now.isoformat()},
            {"action": "create", "status": "completed", "backup_id": "day-13",
             "sha256": "b" * 64, "artifact_path": "/backups/day-13.tar.gz",
             "completed_at": (now - timedelta(days=13)).isoformat()},
            {"action": "create", "status": "completed", "backup_id": "day-16",
             "sha256": "c" * 64, "artifact_path": "/backups/day-16.tar.gz",
             "completed_at": (now - timedelta(days=16)).isoformat()},
            {"action": "create", "status": "completed", "backup_id": "no-date",
             "sha256": "d" * 64, "artifact_path": "/backups/no-date.tar.gz",
             "completed_at": None},
        ]
        self.repo.list_jobs = Mock(return_value=jobs)
        with patch.dict(os.environ, {
            "DSM_BACKUP_RETENTION_DAYS": "14",
            "DSM_BACKUP_RETENTION_INSTANCE_IDS": "instance",
        }):
            actions = self.repo._single_operational_cleanup("instance", "new")
        self.assertEqual(["day-16"], [item["backup_id"] for item in actions])
        self.repo.request.assert_called_once_with(
            "instance", action="delete", backup_id="day-16",
            reason="age_retention", requested_by="scheduler")

    def test_age_retention_does_not_delete_without_confirmed_replacement(self):
        now = datetime.now(timezone.utc)
        self.repo.list_jobs = Mock(return_value=[
            {"action": "create", "status": "completed", "backup_id": "new",
             "sha256": None, "artifact_path": "/backups/new.tar.gz",
             "completed_at": now.isoformat()},
            {"action": "create", "status": "completed", "backup_id": "last-good",
             "sha256": "b" * 64, "artifact_path": "/backups/last-good.tar.gz",
             "completed_at": (now - timedelta(days=35)).isoformat()},
        ])
        with patch.dict(os.environ, {
            "DSM_BACKUP_RETENTION_DAYS": "14",
            "DSM_BACKUP_RETENTION_INSTANCE_IDS": "instance",
        }):
            self.assertEqual([], self.repo._single_operational_cleanup("instance", "new"))
        self.repo.request.assert_not_called()

    def test_age_retention_is_opt_in_per_instance(self):
        now = datetime.now(timezone.utc)
        self.repo.list_jobs = Mock(return_value=[
            {"action": "create", "status": "completed", "backup_id": "new",
             "sha256": "a" * 64, "artifact_path": "/backups/new.tar.gz",
             "completed_at": now.isoformat()},
            {"action": "create", "status": "completed", "backup_id": "old",
             "sha256": "b" * 64, "artifact_path": "/backups/old.tar.gz",
             "completed_at": (now - timedelta(days=1)).isoformat()},
        ])
        with patch.dict(os.environ, {
            "DSM_BACKUP_RETENTION_DAYS": "14",
            "DSM_BACKUP_RETENTION_INSTANCE_IDS": "other",
        }):
            self.assertEqual(["old"], [
                x["backup_id"] for x in self.repo._single_operational_cleanup("instance", "new")])
        self.repo.request.assert_called_once_with(
            "instance", action="delete", backup_id="old",
            reason="operational_retention", requested_by="scheduler")

    def test_partial_or_invalid_age_policy_must_fail_closed(self):
        bad_policies = [
            {"DSM_BACKUP_RETENTION_DAYS": "14", "DSM_BACKUP_RETENTION_INSTANCE_IDS": ""},
            {"DSM_BACKUP_RETENTION_DAYS": "", "DSM_BACKUP_RETENTION_INSTANCE_IDS": "instance"},
            {"DSM_BACKUP_RETENTION_DAYS": "-1", "DSM_BACKUP_RETENTION_INSTANCE_IDS": "instance"},
            {"DSM_BACKUP_RETENTION_DAYS": "366", "DSM_BACKUP_RETENTION_INSTANCE_IDS": "instance"},
            {"DSM_BACKUP_RETENTION_DAYS": "14", "DSM_BACKUP_RETENTION_INSTANCE_IDS": "../unsafe"},
        ]
        for policy in bad_policies:
            with self.subTest(policy=policy), patch.dict(os.environ, policy):
                with self.assertRaises(ValueError):
                    self.repo._single_operational_cleanup("instance", "new")
        self.repo.request.assert_not_called()

    def test_controller_sends_age_policy_to_agent_without_auto_prune(self):
        self.repo.schedule_due = Mock(return_value=[])
        self.repo.list_jobs = Mock(return_value=[{
            "command_id": "cmd-1", "action": "create",
            "instance_id": "instance", "backup_id": None,
            "reason": "schedule", "requested_by": "scheduler",
        }])
        self.repo.get_policy = Mock(return_value={
            "kind": "CapivaraBackupPolicy", "retention_count": 7,
            "mode": "full", "compression": "gzip",
        })
        with patch.dict(os.environ, {
            "DSM_BACKUP_RETENTION_DAYS": "14",
            "DSM_BACKUP_RETENTION_INSTANCE_IDS": "instance",
        }):
            commands = self.repo.commands_for_agent("agent-test")
        self.assertEqual(1, len(commands))
        self.assertEqual(14, commands[0]["policy"]["retention_days"])
        self.assertTrue(commands[0]["policy"]["keep_single_operational"])
        self.assertEqual(7, commands[0]["policy"]["retention_count"])

    def test_age_retention_preserves_last_backup_even_if_older_than_window(self):
        now = datetime.now(timezone.utc)
        self.repo.list_jobs = Mock(return_value=[
            {"action": "create", "status": "completed", "backup_id": "only-good",
             "sha256": "f" * 64, "artifact_path": "/backups/only-good.tar.gz",
             "completed_at": (now - timedelta(days=40)).isoformat()},
        ])
        with patch.dict(os.environ, {
            "DSM_BACKUP_RETENTION_DAYS": "14",
            "DSM_BACKUP_RETENTION_INSTANCE_IDS": "instance",
        }):
            self.assertEqual([], self.repo._single_operational_cleanup("instance", "only-good"))
        self.repo.request.assert_not_called()

    def test_agents_defer_pruning_until_controller_ack(self):
        linux = (ROOT / "agents/linux/runtime/backup_client.py").read_text()
        windows = (ROOT / "agents/windows/runtime/backup_client.py").read_text()
        for platform, code in (("linux", linux), ("windows", windows)):
            with self.subTest(platform=platform):
                self.assertIn('not policy.get("keep_single_operational")', code)


if __name__ == "__main__":
    unittest.main()
