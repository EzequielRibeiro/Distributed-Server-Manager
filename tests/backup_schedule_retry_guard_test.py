"""Prevent failed scheduled backups from generating repeated archives."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "database"))
from backup_repository import BackupRepository


class FailedBackupScheduleGuardTest(unittest.TestCase):
    def setUp(self):
        self.schedule = {"enabled": True, "schedule_time": "12:00",
                         "schedule_timezone": "America/Sao_Paulo"}
        self.now = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)

    def test_failed_scheduled_attempt_blocks_retries_same_day(self):
        jobs = [{"action": "create", "reason": "schedule",
                 "status": "failed", "created_at": "2026-11-20T15:01:00Z"}]
        self.assertFalse(BackupRepository._workspace_due(self.schedule, jobs, self.now))

    def test_pending_scheduled_attempt_blocks_retries_same_day(self):
        jobs = [{"action": "create", "reason": "schedule",
                 "status": "pending", "created_at": "2026-11-20T15:01:00Z"}]
        self.assertFalse(BackupRepository._workspace_due(self.schedule, jobs, self.now))

    def test_previous_day_failed_attempt_allows_new_day(self):
        jobs = [{"action": "create", "reason": "schedule",
                 "status": "failed", "created_at": "2026-11-19T15:01:00Z"}]
        self.assertTrue(BackupRepository._workspace_due(self.schedule, jobs, self.now))

    def test_customer_failure_does_not_suppress_scheduled_backup(self):
        jobs = [{"action": "create", "reason": "customer",
                 "status": "failed", "created_at": "2026-11-20T15:01:00Z"}]
        self.assertTrue(BackupRepository._workspace_due(self.schedule, jobs, self.now))

    def test_successful_customer_backup_suppresses_scheduled_duplicate(self):
        jobs = [{"action": "create", "reason": "customer", "status": "completed",
                 "completed_at": "2026-11-20T15:01:00Z"}]
        self.assertFalse(BackupRepository._workspace_due(self.schedule, jobs, self.now))


if __name__ == "__main__":
    unittest.main()
