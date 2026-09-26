#!/usr/bin/env python3
"""Regression tests for the Customer deletion area's auth and backup gates."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
import deleted_backup_vault_http as endpoint

CUSTOMER = {"username": "owner", "role": "customer", "scope_id": "cli-000001"}
ADMIN = {"username": "admin", "role": "admin", "scope_id": "controller"}


def handler_for(authenticate=lambda headers: CUSTOMER, payload=None, *, path=endpoint.DELETE_PATH):
    class Handler:
        def __init__(self):
            self.path = path
            self.headers = {"X-Capivara-Auth-Area": "customer"}
            self.payload = payload or {}
            self.response = None

        def do_GET(self): raise AssertionError("Unexpected GET fallback")
        def do_POST(self): raise AssertionError("Unexpected POST fallback")
        def read_json_body(self): return self.payload
        def send_json(self, status, body): self.response = (status, body)
        def unauthorized(self): self.response = (401, {"error": "unauthorized"})
        def forbidden(self): self.response = (403, {"error": "forbidden"})

    legacy = SimpleNamespace(DashboardHandler=Handler, DSM_ROOT=ROOT,
        DATABASE_FILE="unused", dashboard_repository=lambda unused: SimpleNamespace(backend=object()))
    endpoint.install_deleted_backup_vault_http(legacy, authenticate)
    return Handler()


class CustomerDeletionAuthorizationTest(unittest.TestCase):
    def test_customer_cookie_wins_when_admin_cookie_also_exists(self):
        areas = []
        def session(headers, *, area="controller"):
            areas.append(area)
            return CUSTOMER if area == "customer" else ADMIN
        class Vault:
            def __init__(self, *args): pass
            def list_for_customer(self, customer_id):
                self_customer_ids.append(customer_id)
                return []
        self_customer_ids = []
        with patch.object(endpoint, "session_user_from_headers", side_effect=session), \
             patch.object(endpoint, "resolve_customer_reference", return_value=1), \
             patch.object(endpoint, "DeletedBackupVaultRepository", Vault):
            handler = handler_for(path=endpoint.LIST_PATH)
            handler.do_GET()
        self.assertEqual(handler.response, (200, {"backups": []}))
        self.assertEqual(areas, ["customer"])
        self.assertEqual(self_customer_ids, [1])

    def test_controller_cookie_cannot_authenticate_customer_endpoint(self):
        def session(headers, *, area="controller"):
            return ADMIN if area == "controller" else None
        with patch.object(endpoint, "session_user_from_headers", side_effect=session):
            handler = handler_for(authenticate=lambda headers: None, path=endpoint.LIST_PATH)
            handler.do_GET()
        self.assertEqual(handler.response[0], 401)

    def _delete(self, forbidden_permission=None, *, final_backup=True):
        class Workspace:
            def __init__(self, *args): pass
            def require(self, user, instance_id, permission):
                called.append(permission)
                if permission == forbidden_permission:
                    raise PermissionError(permission)
                return {"id": instance_id, "name": "Servidor Um", "agent_id": "agent-one"}
        called = []
        started, queued = [], []
        class Vault:
            def __init__(self, *args): pass
            def start(self, *args, **kwargs):
                started.append(True)
                return {"vault_id": "vault-one"}, False
        class Runtime:
            def __init__(self, *args): pass
            def enqueue(self, **kwargs):
                queued.append(kwargs)
                return {"command_id": "command-one", "status": "pending"}
        with patch.object(endpoint, "session_user_from_headers", return_value=CUSTOMER), \
             patch.object(endpoint, "resolve_customer_reference", return_value=1), \
             patch.object(endpoint, "CustomerInstanceWorkspaceService", Workspace), \
             patch.object(endpoint, "DeletedBackupVaultRepository", Vault), \
             patch.object(endpoint, "AgentInstanceRuntimeRepository", Runtime):
            handler = handler_for(payload={
                "instance_id": "instance-one", "confirmation": "Servidor Um",
                "final_backup": final_backup,
            })
            handler.do_POST()
        return handler.response, called, started, queued

    def test_backup_requires_both_backup_permissions(self):
        for denied in ("backup.create", "backup.download"):
            with self.subTest(denied=denied):
                response, checked, started, queued = self._delete(denied)
                self.assertEqual(response[0], 403)
                self.assertEqual(response[1]["error"], "final_backup_permission_required")
                self.assertIn(denied, checked)
                self.assertEqual(started, [])
                self.assertEqual(queued, [])

    def test_delete_permission_is_never_bypassed(self):
        response, checked, started, queued = self._delete("instance.delete", final_backup=False)
        self.assertEqual(response, (403, {"error": "forbidden"}))
        self.assertEqual(checked, ["instance.delete"])
        self.assertFalse(started or queued)

    def test_delete_without_backup_preserves_delete_gate(self):
        response, checked, started, queued = self._delete("backup.create", final_backup=False)
        self.assertEqual(response[0], 202)
        self.assertEqual(response[1]["mode"], "remove")
        self.assertEqual(checked, ["instance.delete"])
        self.assertFalse(started)
        self.assertEqual(queued[0]["action"], "remove")

    def test_backup_path_allowed_when_both_permissions_present(self):
        response, checked, started, queued = self._delete()
        self.assertEqual(response[0], 202)
        self.assertEqual(response[1]["mode"], "backup_then_remove")
        self.assertEqual(checked, ["instance.delete", "backup.create", "backup.download"])
        self.assertTrue(started)
        self.assertFalse(queued)

    def test_frontend_does_not_default_to_backup_without_permissions(self):
        source = (ROOT / "dashboard/web/customer-instance-delete.js").read_text()
        self.assertIn('permissions.has("backup.create")&&permissions.has("backup.download")', source)
        self.assertIn('canFinalBackup?"checked":"disabled"', source)
        self.assertIn('if(e.status===403){status("Não foi possível confirmar', source)
        self.assertIn("throw e}}status(", source)


if __name__ == "__main__":
    unittest.main()
