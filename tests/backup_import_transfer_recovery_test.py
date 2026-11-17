#!/usr/bin/env python3
"""Recovered backup imports: tenant-scoped HTTP listing and explicit restore gate."""
from __future__ import annotations
import io
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime,timedelta,timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
for d in (ROOT/"database",ROOT/"dashboard"):
    if str(d) not in sys.path:sys.path.insert(0,str(d))
from backend import DatabaseConfig
from backend_factory import create_backend
from artifact_transfer_repository import ArtifactTransferRepository
from artifact_transfer_http import install_artifact_transfer_http
from backup_repository import BackupRepository
from customer_instance_workspace_service import CustomerInstanceWorkspaceService

class BackupImportRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="dsm-import-recovery-")
        self.root=Path(self.temp.name)
        self.controller=self.root/"controller"
        self.controller.mkdir()
        self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(self.root/"test.db")))
        self.backend.initialize()
        with self.backend.transaction() as db:
            db.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("cnode","Controller","controller"))
            db.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("anode","Agent","agent"))
            db.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller","cnode","Controller"))
            db.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-a","controller","anode","Agent","active"))
            self.customer_id=db.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("controller","Owner")).lastrowid
            self.other_customer_id=db.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("controller","Other")).lastrowid
            db.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",
                       ("dayz-sandbox","anode","dayz","DayZ isolated","stopped","controller","agent-a",self.customer_id))
        self.transfers=ArtifactTransferRepository(self.backend,self.controller)
        self.backups=BackupRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def completed_import(self,name="backup.tar.gz",customer_id=None):
        item=self.transfers.create(
            agent_id="agent-a",instance_id="dayz-sandbox",
            customer_id=customer_id if customer_id is not None else self.customer_id,
            direction="controller_to_agent",purpose="backup_import",
            filename=name,destination_ref="import-"+name.replace(".","-"),
            requested_by="test")
        data=b"validated-synthetic-backup"
        self.transfers.stage_from_controller(item["transfer_id"],io.BytesIO(data),len(data))
        command=self.transfers.command_for_agent("agent-a")
        self.assertEqual(command["transfer_id"],item["transfer_id"])
        return self.transfers.apply_agent_result("agent-a",{
            "transfer_id":item["transfer_id"],"status":"completed",
            "transferred_bytes":len(data),
        })

    def test_only_completed_unexpired_imports_with_destination_are_listed(self):
        completed=self.completed_import()
        old=self.completed_import("expired.tar.gz")
        with self.backend.transaction() as db:
            past=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat().replace("+00:00","Z")
            db.execute("UPDATE artifact_transfers SET expires_at=? WHERE transfer_id=?",
                       (past,old["transfer_id"]))
        staged=self.transfers.create(agent_id="agent-a",instance_id="dayz-sandbox",
            customer_id=self.customer_id,direction="controller_to_agent",purpose="backup_import",
            filename="staging.tar.gz",destination_ref="import-staging",requested_by="test")
        records=self.transfers.list_completed_backup_imports("dayz-sandbox")
        self.assertEqual([x["transfer_id"] for x in records],[completed["transfer_id"]])
        self.assertNotIn(staged["transfer_id"],[x["transfer_id"] for x in records])

    def test_authenticated_recovery_exposes_only_current_customer_and_requires_explicit_restore(self):
        own=self.completed_import("owner.tar.gz")
        foreign=self.completed_import("foreign.tar.gz",customer_id=self.other_customer_id)
        backend=self.backend
        class Legacy:
            DSM_ROOT=self.controller
            DATABASE_FILE=str(self.root/"test.db")
            dashboard_repository=staticmethod(lambda _filename:SimpleNamespace(backend=backend))
            class DashboardHandler(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def send_json(self,status,value):
                    encoded=json.dumps(value,default=str).encode()
                    self.send_response(status)
                    self.send_header("Content-Type","application/json")
                    self.send_header("Content-Length",str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                def unauthorized(self):self.send_json(401,{"error":"unauthorized"})
                def read_json_body(self):
                    return json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
                def do_GET(self):self.send_json(404,{"error":"not_found"})
                def do_POST(self):self.send_json(404,{"error":"not_found"})
        install_artifact_transfer_http(Legacy,lambda h:{"role":"customer","username":"owner"}
            if h.get("X-Test-Auth")=="owner" else None)
        def require(_service,user,instance_id,permission):
            if instance_id!="dayz-sandbox" or permission!="backup.restore" or user["username"]!="owner":
                raise PermissionError("not authorized")
            return {"id":"dayz-sandbox","agent_id":"agent-a","customer_id":self.customer_id}

        server=ThreadingHTTPServer(("127.0.0.1",0),Legacy.DashboardHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def request(method,path,body=None,authenticated=True):
            connection=HTTPConnection("127.0.0.1",server.server_port,timeout=5)
            data=json.dumps(body).encode() if body is not None else None
            headers={}
            if authenticated:headers["X-Test-Auth"]="owner"
            if data is not None:headers["Content-Type"]="application/json"
            try:
                connection.request(method,path,body=data,headers=headers)
                response=connection.getresponse()
                return response.status,json.loads(response.read())
            finally:connection.close()
        try:
            with patch.object(CustomerInstanceWorkspaceService,"require",require):
                route="/api/customer/artifacts/imports?instance_id=dayz-sandbox"
                self.assertEqual(request("GET",route,authenticated=False)[0],401)
                self.assertEqual(request("GET","/api/customer/artifacts/imports?instance_id=other")[0],403)
                status,data=request("GET",route)
                self.assertEqual(status,200,data)
                self.assertEqual(len(data["imports"]),1)
                item=data["imports"][0]
                self.assertEqual(item["transfer_id"],own["transfer_id"])
                self.assertNotEqual(item["transfer_id"],foreign["transfer_id"])
                self.assertNotIn("controller_path",item)
                self.assertNotIn("requested_by",item)
                self.assertEqual(self.backups.list_jobs(instance_id="dayz-sandbox"),[])
                status,restored=request("POST","/api/customer/artifacts/restore-import",
                                        {"transfer_id":own["transfer_id"]})
                self.assertEqual(status,202,restored)
                self.assertEqual(restored["restore_job"]["action"],"restore")
                self.assertEqual(restored["restore_job"]["backup_id"],own["destination_ref"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_both_views_restore_prior_import_without_reupload(self):
        for filename in ("customer-backup-transfer.js","controller-instance-backup-transfer.js"):
            js=(ROOT/"dashboard/web"/filename).read_text(encoding="utf-8")
            self.assertIn("recoverCompletedImports()",js)
            self.assertIn("/api/customer/artifacts/imports?instance_id=",js)
            self.assertIn("pendingImportedTransfer=restored",js)
            self.assertIn("Pronto para restaurar sem reenviar",js)
            self.assertIn("restore.hidden=!pendingImportedTransfer",js)
            self.assertIn("if(!permissions.has(\"backup.restore\")",js)

if __name__=="__main__":
    unittest.main()
