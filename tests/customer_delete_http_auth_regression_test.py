#!/usr/bin/env python3
"""Customer deletion must use the Customer cookie even with both sessions."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]
for folder in ("dashboard","database","core"):
    sys.path.insert(0,str(ROOT/folder))
import deleted_backup_vault_http as http

CUSTOMER={"username":"client","role":"customer","scope_id":"CLI-000001"}
CONTROLLER={"username":"admin","role":"admin","scope_id":""}
INSTANCE={"id":"instance-one","name":"Servidor Um","agent_id":"agent-one"}

class Handler:
    def __init__(self, *, backup=False):
        self.path="/api/customer/instance/delete"
        self.headers={"Cookie":"capivara_controller_session=abc; capivara_customer_session=xyz","X-Capivara-Auth-Area":"customer"}
        self.payload={"instance_id":"instance-one","confirmation":"instance-one","final_backup":backup}
        self.sent=None
    def read_json_body(self): return self.payload
    def send_json(self,status,data): self.sent=(status,data)
    def unauthorized(self): self.sent=(401,{"error":"unauthorized"})
    def forbidden(self): self.sent=(403,{"error":"forbidden"})
    def do_GET(self): raise AssertionError("unexpected GET")
    def do_POST(self): raise AssertionError("unexpected fallback POST")

class CustomerDeleteAuthRegressionTest(unittest.TestCase):
    def setUp(self):
        self.service=MagicMock()
        self.service.require.return_value=INSTANCE
        self.runtime=MagicMock()
        self.runtime.enqueue.return_value={"command_id":"cmd-test","status":"queued"}
        self.vault=MagicMock()
        self.vault.start.return_value=({"vault_id":"vault-test","status":"backup_pending"},False)
        legacy=SimpleNamespace(DashboardHandler=type("TestHandler",(Handler,),{}),
            DSM_ROOT=ROOT,DATABASE_FILE=ROOT/"unused.db",
            dashboard_repository=lambda _: SimpleNamespace(backend=object()))
        self.legacy=legacy
        self.patches=[
            patch.object(http,"CustomerInstanceWorkspaceService",return_value=self.service),
            patch.object(http,"AgentInstanceRuntimeRepository",return_value=self.runtime),
            patch.object(http,"DeletedBackupVaultRepository",return_value=self.vault)]
        for item in self.patches: item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
    def invoke(self, *, customer=True, backup=False):
        def session(headers, *, area="controller"):
            return CUSTOMER if area=="customer" and customer else CONTROLLER if area=="controller" else None
        with patch.object(http,"session_user_from_headers",side_effect=session) as lookup:
            http.install_deleted_backup_vault_http(self.legacy,lambda _:None)
            handler=self.legacy.DashboardHandler(backup=backup)
            handler.do_POST()
        return handler.sent,lookup
    def test_dual_session_uses_customer_and_only_queues_removal(self):
        (code,body),lookup=self.invoke(customer=True)
        self.assertEqual(code,202)
        self.assertEqual(body["mode"],"remove")
        lookup.assert_called_once()
        self.assertEqual(lookup.call_args.kwargs,{"area":"customer"})
        self.service.require.assert_called_once_with(CUSTOMER,"instance-one","instance.delete")
        self.runtime.enqueue.assert_called_once()
    def test_controller_cookie_alone_cannot_delete_customer_instance(self):
        (code,_),lookup=self.invoke(customer=False)
        self.assertEqual(code,401)
        lookup.assert_called_once()
        self.runtime.enqueue.assert_not_called()
    def test_missing_backup_permissions_does_not_start_or_remove(self):
        def require(user,instance,permission):
            if permission=="backup.create": raise PermissionError("backup.create permission required")
            return INSTANCE
        self.service.require.side_effect=require
        (code,body),_=self.invoke(backup=True)
        self.assertEqual(code,403)
        self.assertEqual(body["error"],"backup_permission_required")
        self.assertIn("backup final",body["message"])
        self.runtime.enqueue.assert_not_called()
        self.vault.start.assert_not_called()
    def test_missing_backup_download_permission_is_explained(self):
        def require(user,instance,permission):
            if permission=="backup.download": raise PermissionError("backup.download permission required")
            return INSTANCE
        self.service.require.side_effect=require
        (code,body),_=self.invoke(backup=True)
        self.assertEqual((code,body["error"]),(403,"backup_permission_required"))
        self.vault.start.assert_not_called()
        self.runtime.enqueue.assert_not_called()
    def test_frontend_disables_unavailable_final_backup(self):
        js=(ROOT/"dashboard/web/customer-instance-delete.js").read_text(encoding="utf-8")
        self.assertIn('permissions.has("backup.create")&&permissions.has("backup.download")',js)
        self.assertIn('canFinalBackup?"checked":"disabled"',js)
        self.assertIn("A exclusão sem backup é irreversível",js)
    def test_authorized_final_backup_keeps_backup_before_removal(self):
        (code,body),_=self.invoke(backup=True)
        self.assertEqual(code,202)
        self.assertEqual(body["mode"],"backup_then_remove")
        self.vault.start.assert_called_once()
        self.runtime.enqueue.assert_not_called()

if __name__=="__main__": unittest.main()
