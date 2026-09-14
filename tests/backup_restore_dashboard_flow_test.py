#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackupRestoreDashboardFlowTest(unittest.TestCase):
    def test_restore_surface_lists_all_completed_backups(self):
        js = (ROOT / "dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
        self.assertIn('availableBackupJobs', js)
        self.assertIn('x.action==="create"&&x.status==="completed"&&x.backup_id', js)
        self.assertIn('x.action==="delete"&&x.status==="completed"&&x.backup_id', js)
        self.assertNotIn('.slice(0,1)', js)
        self.assertIn('job.completed_at||job.created_at', js)

    def test_recent_backup_operations_expire_only_from_the_operational_view(self):
        js = (ROOT / "dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
        self.assertIn("RECENT_OPERATION_WINDOW_MS=72*60*60*1000", js)
        self.assertIn("recentOperationalJobs", js)
        self.assertIn('status==="pending"||status==="running"', js)
        self.assertIn('status!=="failed"', js)
        self.assertIn("now-timestamp<=RECENT_OPERATION_WINDOW_MS", js)
        self.assertIn("O histórico completo permanece preservado", js)
        self.assertNotIn("DELETE FROM backup_jobs", js)

    def test_restore_requires_explicit_confirmation_and_explains_impact(self):
        js = (ROOT / "dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
        self.assertIn('restoreWarning', js)
        self.assertIn('confirm(restoreWarning', js)
        self.assertIn('substituirá o estado atual da instância', js)
        self.assertIn('staging', js)
        self.assertIn('rollback', js)

    def test_external_backup_upload_and_restore_are_separate_actions(self):
        js = (ROOT / "dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
        self.assertIn('>Enviar backup</button>', js)
        self.assertIn('>Restaurar backup</button>', js)
        self.assertIn('backup-transfer-upload', js)
        self.assertIn('backup-transfer-restore-import', js)
        self.assertIn('pendingImportedTransfer=completed', js)
        self.assertIn('restore.hidden=!pendingImportedTransfer', js)
        self.assertIn('send.disabled=!allowed||!selected', js)
        self.assertIn('recebido e validado; pronto para restaurar', js)
        self.assertNotIn('>Importar e restaurar</button>', js)

        upload = js[js.index("async function uploadBackup"):js.index("async function restoreImportedBackup")]
        restore = js[js.index("async function restoreImportedBackup"):js.index("function button(")]
        self.assertIn('/api/customer/artifacts/backup-import', upload)
        self.assertIn('/api/customer/artifacts/upload?', upload)
        self.assertNotIn('/api/customer/artifacts/restore-import', upload)
        self.assertIn('/api/customer/artifacts/restore-import', restore)
        self.assertIn('confirm(restoreWarning', restore)

    def test_customer_and_admin_share_permission_guarded_backend(self):
        service = (ROOT / "dashboard/customer_instance_workspace_service.py").read_text(encoding="utf-8")
        http = (ROOT / "dashboard/customer_instance_workspace_http.py").read_text(encoding="utf-8")
        self.assertIn('role in {"admin","controller"}', service)
        self.assertIn('"restore":"backup.restore"', service)
        self.assertIn('"delete":"backup.delete"', service)
        self.assertIn('list_effective_jobs(instance_id=instance_id,limit=100)', service)
        compact_http = "".join(http.split())
        self.assertIn('{"customer","admin","controller"}', compact_http)

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
