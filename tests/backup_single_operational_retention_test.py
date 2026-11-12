"""Single-operational backup retention must wait for committed replacement."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

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

    def test_agents_defer_pruning_until_controller_ack(self):
        linux = (ROOT / "agents/linux/runtime/backup_client.py").read_text()
        windows = (ROOT / "agents/windows/runtime/backup_client.py").read_text()
        for platform, code in (("linux", linux), ("windows", windows)):
            with self.subTest(platform=platform):
                self.assertIn('not policy.get("keep_single_operational")', code)


if __name__ == "__main__":
    unittest.main()
