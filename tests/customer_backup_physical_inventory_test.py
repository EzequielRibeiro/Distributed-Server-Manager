"""Customer-visible physical backup inventory and explicit deletion contracts."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
for directory in ("dashboard", "database", "core"):
    path = str(ROOT / directory)
    if path not in sys.path:
        sys.path.insert(0, path)

from customer_instance_workspace_service import CustomerInstanceWorkspaceService


class CustomerBackupPhysicalInventoryTest(unittest.TestCase):
    def setUp(self):
        self.service = CustomerInstanceWorkspaceService.__new__(CustomerInstanceWorkspaceService)
        self.service.require = Mock(return_value={"agent_id": "agent-1"})
        self.service.backups = Mock()
        self.service.backups.request.return_value = {"command_id": "delete-1"}
        self.sample = {
            "instance_id": "cli-000001-dayz-002",
            "backup_physical_catalog": {
                "status": "ok", "instance_id": "cli-000001-dayz-002",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "total_files": 2, "total_bytes": 9_000_000_000,
                "truncated": False,
                "files": [
                    {"filename": "import-416.tar.gz", "backup_id": "import-416",
                     "size_bytes": 8_000_000_000, "kind": "archive_unverified"},
                    {"filename": "unknown.part", "backup_id": None,
                     "size_bytes": 1_000_000_000, "kind": "other_file"},
                ]
            }
        }
        self.service._location = Mock(return_value={"agent_metadata": {
            "instance_telemetry": [self.sample]
        }})
        self.user = {"username": "customer"}
        self.iid = "cli-000001-dayz-002"

    def test_imported_archive_is_listed_separately_from_completed_db_jobs(self):
        catalog = self.service.backup_catalog(self.user, self.iid)
        self.assertEqual(catalog["total_bytes"], 9_000_000_000)
        self.assertEqual(catalog["total_files"], 2)
        self.assertEqual(catalog["files"][0]["backup_id"], "import-416")
        self.assertEqual(catalog["files"][0]["physical_verification"], "not_checked")
        self.assertNotIn("artifact_path", catalog["files"][0])

    def test_manual_delete_queues_only_a_fresh_listed_archive(self):
        result = self.service.request_backup(self.user, self.iid, "delete", "import-416")
        self.assertEqual(result["command_id"], "delete-1")
        self.service.backups.request.assert_called_once_with(
            self.iid, action="delete", backup_id="import-416",
            reason="customer", requested_by="customer",
        )

    def test_refuse_guessed_id_partial_or_stale_catalog(self):
        for bid in ("guessed", "unknown.part"):
            with self.subTest(bid=bid), self.assertRaises(ValueError):
                self.service.request_backup(self.user, self.iid, "delete", bid)
        self.sample["backup_physical_catalog"]["checked_at"] = "2020-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "stale"):
            self.service.request_backup(self.user, self.iid, "delete", "import-416")
        self.service.backups.request.assert_not_called()

    def test_cannot_list_archive_of_different_instance_or_agent(self):
        self.sample["instance_id"] = "cli-000001-dayz-003"
        result = self.service.backup_catalog(self.user, self.iid)
        self.assertEqual(result["status"], "unavailable")
        with self.assertRaises(ValueError):
            self.service.request_backup(self.user, self.iid, "delete", "import-416")
        self.service.backups.request.assert_not_called()

    def test_permission_required_even_for_inventory(self):
        self.service.require.side_effect = PermissionError("backup.read denied")
        with self.assertRaises(PermissionError):
            self.service.backup_catalog(self.user, self.iid)

    def test_customer_ui_has_explicit_confirmation_and_legacy_fallback(self):
        source = (ROOT / "dashboard/web/customer-instance-v2.js").read_text()
        self.assertIn("physical_catalog", source)
        self.assertIn("Arquivo físico sem operação de criação registrada", source)
        self.assertIn("confirm(", source)
        self.assertIn('can("backup.delete")', source)
        self.assertIn('can("backup.restore")', source)


if __name__ == "__main__":
    unittest.main()
