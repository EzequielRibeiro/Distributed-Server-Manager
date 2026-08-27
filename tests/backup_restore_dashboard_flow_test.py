#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackupRestoreDashboardFlowTest(unittest.TestCase):
    def test_restore_surface_lists_all_completed_backups(self):
        js = (ROOT / "dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
        self.assertIn('filter(x=>x.action==="create"&&x.status==="completed"&&x.backup_id)', js)
        self.assertNotIn('.slice(0,1)', js)
        self.assertIn('job.completed_at||job.created_at', js)

    def test_restore_requires_explicit_confirmation_and_explains_impact(self):
        js = (ROOT / "dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
        self.assertIn('restoreWarning', js)
        self.assertIn('confirm(restoreWarning', js)
        self.assertIn('substituirá o estado atual da instância', js)
        self.assertIn('staging', js)
        self.assertIn('rollback', js)

    def test_customer_and_admin_share_permission_guarded_backend(self):
        service = (ROOT / "dashboard/customer_instance_workspace_service.py").read_text(encoding="utf-8")
        http = (ROOT / "dashboard/customer_instance_workspace_http.py").read_text(encoding="utf-8")
        self.assertIn('role in {"admin","controller"}', service)
        self.assertIn('"restore":"backup.restore"', service)
        self.assertIn('"delete":"backup.delete"', service)
        self.assertIn('{"customer","admin","controller"}', http)

    def test_selected_backup_can_be_downloaded_and_restored(self):
        js = (ROOT / "dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
        self.assertIn('exportBackup(job.backup_id)', js)
        self.assertIn('requestBackupAction("restore",job.backup_id)', js)
        self.assertIn('permissions.has("backup.download")', js)
        self.assertIn('permissions.has("backup.restore")', js)

    def test_safety_backup_and_progress_are_visible(self):
        js = (ROOT / "dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
        self.assertIn('Criar backup de segurança', js)
        self.assertIn('waitBackupJob', js)
        self.assertIn('pending:"Pendente"', js)
        self.assertIn('running:"Em execução"', js)
        self.assertIn('failed:"Falhou"', js)
        self.assertIn('setInterval(()=>refresh()', js)


if __name__ == "__main__":
    unittest.main()
