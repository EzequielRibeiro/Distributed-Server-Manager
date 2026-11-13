"""Read-only official Server Pack preview through the customer cookie HTTP router.

The opt-in ZIP is genuine; CurseForge API responses and transfer receipt are
test fixtures, so this does NOT attest live upload/Agent transfer.
"""
from __future__ import annotations
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"tests",ROOT/"dashboard",ROOT/"core",ROOT/"database"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
import controller_session
import customer_content_http
from customer_content_upload_service import CustomerContentUploadService
from customer_serverpack_service import build_serverpack_bundle
import minecraft_serverpack_pending_publication_atomic_test as atomic_fixture

IID="pr855-controller-atomic"
AGENT="pr839-isolated-agent"
USER="dsm1013-preview-customer"
TRANSFER="transfer-1013-preview"
SHA_014="b8635562de0931eb5cadb51954c0fb78658033928ef54b5f73be6cae5c8897fa"
NAME="ServerFiles-0.14.0-beta.zip"

class CustomerOfficialPreviewSessionE2E(unittest.TestCase):
    def setUp(self):
        folder=os.environ.get("DSM_1013_OFFICIAL_PACK_ROOT")
        if not folder:
            self.skipTest("Requires explicit official ZIP directory, read only")
        self.zip=Path(folder)/NAME
        if not self.zip.is_file():
            raise AssertionError("Official 0.14 Server Pack archive missing")
        with self.zip.open("rb") as f:
            self.assertEqual(hashlib.file_digest(f,"sha256").hexdigest(),SHA_014)
        with self.zip.open("rb") as f:
            sha1=hashlib.file_digest(f,"sha1").hexdigest()
        self.fixture=atomic_fixture.AtomicPendingPublicationTest(
            methodName="test_completed_agent_result_publishes_bundle_in_same_completion_transaction")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.content.put_bundle(
            atomic_fixture.parent("0.13.0-beta"),
            atomic_fixture.bundle("0.13.0-beta","26.1.2.124","a"),
            [atomic_fixture.child("0.13.0-beta","26.1.2.124","a")],
            requested_by="customer")
        with self.fixture.backend.transaction() as con:
            con.execute("UPDATE instances SET build_id=? WHERE id=?",
                        ("26.1.2.124",IID))
            con.execute("INSERT INTO dashboard_users (username,password_hash,role,scope_id,active) VALUES (?,?,?,?,?)",
                        (USER,"not-a-login-secret","customer","isolated",1))
            con.execute("INSERT INTO instance_access (username,instance_id,permission_profile) VALUES (?,?,?)",
                        (USER,IID,"manager"))
        self.assertEqual(self.fixture.content.bundle_history(IID,"atm11")[0]["revision"],2)
        self.transfers=SimpleNamespace()
        self.transfer={"transfer_id":TRANSFER,"instance_id":IID,"agent_id":AGENT,
            "direction":"controller_to_agent","purpose":"content_upload","status":"completed",
            "filename":NAME,"sha256":SHA_014,"size_bytes":self.zip.stat().st_size,
            "destination_ref":f"quarantine/{IID}/{TRANSFER}/{NAME}"}
        self.transfers.get=lambda _id:dict(self.transfer)
        self.transfers.controller_artifact=lambda _id:(self.zip,dict(self.transfer))
        self.request_count=0
        def requester(url,headers):
            self.request_count+=1
            assert headers=={"x-api-key":"test-only-provider-metadata"}
            if "/categories?" in url:
                return {"data":[{"id":4471,"slug":"modpacks",
                     "name":"Modpacks","isClass":True}]}
            if url.endswith("/mods/1148445"):
                return {"data":{"id":1148445,"gameId":432,"classId":4471,
                    "name":"All the Mods 11","allowModDistribution":True}}
            if url.endswith("/mods/1148445/files/9426897"):
                return {"data":{"id":9426897,"fileName":NAME,
                    "isAvailable":True,"fileLength":self.zip.stat().st_size,
                    "gameVersions":["26.1.2","NeoForge"],
                    "hashes":[{"algo":1,"value":sha1}]}}
            raise AssertionError(f"unexpected test provider lookup: {url}")
        self.backend=self.fixture.backend
        service=CustomerContentUploadService(self.backend,ROOT)
        service.transfers=self.transfers
        # Fixture permits managed content; authentication and authorization
        # are still resolved by the real DB and real cookie router.
        original=service.workspace._contract_policy
        policy=SimpleNamespace(external_upload_allowed=True,
            modifications_allowed=True,modpacks_allowed=True,mods_allowed=True)
        service.workspace._contract_policy=lambda context,details:(original(context,details)[0],policy)
        self.service=service
        self.patchers=[
            patch.object(customer_content_http,"CustomerContentUploadService",
                side_effect=lambda backend,root:self.service),
            patch("customer_content_upload_service.build_serverpack_bundle",
                partial(build_serverpack_bundle,requester=requester,
                    load_secret=lambda _path:"test-only-provider-metadata")),
            patch.object(controller_session,"SESSION_FILE",
                Path(self.fixture.temp.name)/"customer-browser-sessions.json"),
        ]
        for obj in self.patchers:obj.start()
        self.addCleanup(self._cleanup_patches)
        with controller_session._lock:
            controller_session._sessions.clear()
            controller_session._loaded=False
        self.customer_token=controller_session.create_session({
            "username":USER,"role":"customer",
            "scope_id":"isolated","customer_id":1},area="customer")
        self.admin_token=controller_session.create_session({
            "username":"isolated-admin","role":"admin",
            "scope_id":"isolated"},area="controller")
        backend=self.backend
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_args):pass
            def send_json(self,status,payload):
                data=json.dumps(payload,default=str).encode()
                self.send_response(status)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def unauthorized(self):self.send_json(401,{"error":"unauthorized"})
            def forbidden(self):self.send_json(403,{"error":"forbidden"})
            def read_json_body(self):
                size=int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(size))
            def do_POST(self):self.send_json(404,{"error":"not_found"})
            def do_GET(self):self.send_json(404,{"error":"not_found"})
        legacy=SimpleNamespace(DashboardHandler=Handler,DSM_ROOT=ROOT,
            DATABASE_FILE="unused",
            dashboard_repository=lambda _p:SimpleNamespace(backend=backend))
        customer_content_http.install_customer_content_http(legacy,
            authenticate=lambda headers:None)
        self.http=ThreadingHTTPServer(("127.0.0.1",0),legacy.DashboardHandler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_http)

    def _cleanup_patches(self):
        with controller_session._lock:
            controller_session._sessions.clear()
            controller_session._loaded=False
        for p in reversed(self.patchers):p.stop()
    def _stop_http(self):
        self.http.shutdown();self.http.server_close();self.thread.join(timeout=5)
    def call(self,path,payload=None,*,token=None,as_controller=False):
        cookies={}
        if token:
            cookie=(controller_session.CONTROLLER_SESSION_COOKIE
                if as_controller else controller_session.CUSTOMER_SESSION_COOKIE)
            cookies["Cookie"]=f"{cookie}={token}"
        headers={"X-Capivara-Auth-Area":"customer",**cookies}
        if payload is not None:headers["Content-Type"]="application/json"
        req=Request(f"http://127.0.0.1:{self.http.server_port}"+path,
            method="POST" if payload is not None else "GET",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers)
        try:
            with urlopen(req,timeout=90) as res:return res.status,json.load(res)
        except HTTPError as error:return error.code,json.load(error)

    def test_customer_cookie_real_014_zip_preview_revalidate_and_deny_unsafe(self):
        path="/api/customer/instance/workspace/content/upload/preview"
        data={"instance_id":IID,"transfer_id":TRANSFER,
            "content_id":"atm11","content_type":"modpack",
            "metadata":{"display_name":"All the Mods 11",
                "serverpack":{"format":"official-serverpack-v1",
                "curseforge_project_id":"1148445",
                "curseforge_file_id":"9426897",
                "loader_version":"26.1.2.126"}}}
        self.assertEqual(self.call(path,data)[0],401)
        self.assertEqual(self.call(path,data,token=self.admin_token,as_controller=True)[0],401)
        status,response=self.call(path,data,token=self.customer_token)
        self.assertEqual(status,200,response)
        preview=response["serverpack"]
        self.assertEqual(preview["kind"],"CapivaraServerPackPreview")
        self.assertEqual(preview["mod_count"],291)
        self.assertEqual(preview["archive_sha256"],SHA_014)
        self.assertEqual(preview["loader_version"],"26.1.2.126")
        self.assertEqual(preview["source"]["project_id"],"1148445")
        plan=preview["update_plan"]
        self.assertEqual(plan["operation"],"staged_loader_migration_preview")
        self.assertEqual(plan["from_loader_version"],"26.1.2.124")
        self.assertEqual(plan["target_loader_version"],"26.1.2.126")
        self.assertFalse(plan["install_allowed"])
        self.assertEqual(plan["previous_revision"],2)
        self.assertEqual(plan["evidence"]["serverpack_mod_count"],291)
        fingerprint=plan["migration_plan_sha256"]
        self.assertEqual(len(fingerprint),64)
        self.assertEqual(self.fixture.content.bundle_history(IID,"atm11")[0]["revision"],2)
        revalidate="/api/customer/instance/workspace/content/upload/migration/revalidate"
        status,recheck=self.call(revalidate,{**data,"migration_plan_sha256":fingerprint},
            token=self.customer_token)
        self.assertEqual(status,200,recheck)
        self.assertTrue(recheck["migration"]["valid"])
        self.assertFalse(recheck["migration"]["install_allowed"])
        self.assertEqual(recheck["migration"]["migration_plan_sha256"],fingerprint)
        wrong={**data,"migration_plan_sha256":"f"*64}
        status,error=self.call(revalidate,wrong,token=self.customer_token)
        self.assertEqual(status,400,error)
        self.assertEqual(error["error"],"invalid_request")
        self.assertEqual(self.fixture.content.bundle_history(IID,"atm11")[0]["revision"],2)
        self.assertGreaterEqual(self.request_count,6)
        print("SESSION_OFFICIAL_014_PREVIEW_PASS",json.dumps({
            "archive_sha256":SHA_014,"mod_count":291,
            "from_loader":"26.1.2.124","target_loader":"26.1.2.126",
            "authenticated_customer_cookie":True,
            "controller_cookie_rejected":True,
            "readonly_revision":2,
            "revalidated_same_fingerprint":True,
            "mismatch_fingerprint_blocked":True,
            "real_zip_inspection":True,
            "provider_metadata":"controlled_test_response",
            "upload_agent_transfer":"fixture_receipt",
            "production_touched":False,
        },sort_keys=True),flush=True)

if __name__=="__main__":
    unittest.main(verbosity=2)
