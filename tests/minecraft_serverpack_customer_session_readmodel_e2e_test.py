"""Customer cookie/session real HTTP read model after a journaled Server Pack migration.

All state, credential cookies and HTTP listeners exist only in temporary local tests.
"""
from __future__ import annotations
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
for f in (ROOT, ROOT/"tests", ROOT/"database",ROOT/"core",ROOT/"dashboard",ROOT/"agents/linux/runtime",ROOT/"agents/common"):
    if str(f) not in sys.path:sys.path.insert(0,str(f))
from tests.minecraft_serverpack_customer_single_action_e2e_test import SingleCustomerActionToAuthenticatedAckE2E
import controller_session
import customer_content_http
from content_repository import ContentRepository

class CustomerSessionReadmodelE2E(SingleCustomerActionToAuthenticatedAckE2E):
    # The joined transaction is deliberately called once *inside* the HTTP
    # read-model assertion; don't rerun inherited tests as separate cases.
    test_authentic_credentials_493_atomic_and_ack_lost_response_replay = None
    test_one_action_to_physical_swap_controller_cas_authenticated_ack = None

    def setUp(self):
        super().setUp()
        self._session_file_patcher=patch.object(controller_session,"SESSION_FILE",Path(self.root)/"browser-sessions.json")
        self._session_file_patcher.start()
        self.addCleanup(self._session_file_patcher.stop)
        with controller_session._lock:
            controller_session._sessions.clear()
            controller_session._loaded=False
        self.addCleanup(self._cleanup_browser_sessions)
        self.customer="dsm1013-isolated-customer"
        with self.backend.transaction() as con:
            con.execute(
                "INSERT INTO dashboard_users (username,password_hash,role,scope_id,active) VALUES (?,?,?,?,?)",
                (self.customer,"not-a-login-credential","customer","isolated",1))
            con.execute(
                "INSERT INTO instance_access (username,instance_id,permission_profile) VALUES (?,?,?)",
                (self.customer,self.iid,"manager"))
        self.customer_token=controller_session.create_session(
            {"username":self.customer,"role":"customer",
             "scope_id":"isolated","customer_id":1},
            area="customer")
        self.controller_token=controller_session.create_session(
            {"username":"dsm1013-isolated-admin","role":"admin",
             "scope_id":"isolated"},area="controller")
        backend=self.backend
        class Handler(BaseHTTPRequestHandler):
            def send_json(self,status,body):
                raw=json.dumps(body,default=str).encode()
                self.send_response(status)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def log_message(self,*_args):pass
            def unauthorized(self):self.send_json(401,{"error":"unauthorized"})
            def forbidden(self):self.send_json(403,{"error":"forbidden"})
            def read_json_body(self):
                return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            def do_GET(self):self.send_json(404,{"error":"not_found"})
            def do_POST(self):self.send_json(404,{"error":"not_found"})
        legacy=SimpleNamespace(
            DashboardHandler=Handler,DSM_ROOT=ROOT,DATABASE_FILE="unused",
            dashboard_repository=lambda _path:SimpleNamespace(backend=backend))
        customer_content_http.install_customer_content_http(legacy,authenticate=lambda _headers:None)
        self.customer_server=ThreadingHTTPServer(("127.0.0.1",0),legacy.DashboardHandler)
        self.customer_thread=threading.Thread(target=self.customer_server.serve_forever,daemon=True)
        self.customer_thread.start()
        self.addCleanup(self._stop_http)

    def _cleanup_browser_sessions(self):
        with controller_session._lock:
            controller_session._sessions.clear()
            controller_session._loaded=False

    def _stop_http(self):
        self.customer_server.shutdown()
        self.customer_server.server_close()
        self.customer_thread.join(timeout=4)

    def fetch(self,token=None,*,area="customer",instance_id=None,controller=False):
        path="/api/customer/instance/workspace/content?instance_id="+(instance_id or self.iid)
        headers={"X-Capivara-Auth-Area":area}
        if token:
            name=(controller_session.CONTROLLER_SESSION_COOKIE if controller
                  else controller_session.CUSTOMER_SESSION_COOKIE)
            headers["Cookie"]=f"{name}={token}"
        req=Request(f"http://127.0.0.1:{self.customer_server.server_port}"+path,
                    method="GET",headers=headers)
        try:
            with urlopen(req,timeout=15) as res:
                return res.status,json.load(res)
        except HTTPError as error:
            return error.code,json.load(error)

    def test_authenticated_customer_reads_blocked_until_current_runtime_witness(self):
        self.assertEqual(self.fetch()[0],401)
        self.assertEqual(self.fetch("invalid-token")[0],401)
        self.assertEqual(self.fetch(self.controller_token)[0],401)
        self.assertEqual(self.fetch(self.customer_token,area="controller")[0],401)
        before_status,before=self.fetch(self.customer_token)
        self.assertEqual(before_status,200,before)
        self.assertEqual(before["content"][0]["reconciliation"]["status"],"pending")
        super().test_one_action_to_physical_swap_controller_cas_authenticated_ack()
        status,payload=self.fetch(self.customer_token)
        self.assertEqual(status,200,payload)
        self.assertEqual(len(payload["content"]),1)
        item=payload["content"][0]
        self.assertEqual(item["content_id"],"atm11")
        self.assertEqual(item["reconciliation"]["status"],"applied")
        self.assertEqual(item["bundle_summary"]["child_count"],291)
        self.assertEqual(item["bundle_summary"]["absent_child_count"],201)
        self.assertEqual(item["bundle_summary"]["manifest_alignment"],"metadata_aligned")
        self.assertEqual(item["bundle_summary"]["physical_attestation"],"verified")
        self.assertEqual(item["bundle_summary"]["health_gate"],"blocked")
        self.assertEqual(item["bundle_summary"]["health_reason"],"runtime_boot_not_attested")
        self.assertEqual(item["bundle_summary"]["convergence_status"],"pending")
        self.assertFalse(item["actions"]["update"])
        self.assertTrue(item["update"]["rollback_available"])
        # The synthetic contract has no modpack entitlement; effective actions
        # remain denied even when the prior revision exists.
        self.assertFalse(item["actions"]["rollback"])
        self.assertEqual(item["bundle_summary"]["metadata_convergence"],"aligned")
        self.assertEqual(item["bundle_summary"]["current_boot_witness"],"missing")
        self.assertEqual(self.fetch(self.customer_token,instance_id="unknown-instance")[0],403)
        print("SESSION_READMODEL_FAIL_CLOSED_PASS",json.dumps({
            "customer_session_cookie":True,
            "controller_cookie_rejected":True,"anonymous_rejected":True,
            "bundle_revision":3,"mods":291,"absent":201,
            "physical_attestation":"verified",
            "health_gate":"blocked",
            "health_reason":"runtime_boot_not_attested",
            "action_rollback":item["actions"]["rollback"],
            "isolated_sqlite":True,"production_touched":False,
        },sort_keys=True),flush=True)

if __name__=="__main__":
    unittest.main(defaultTest="CustomerSessionReadmodelE2E",verbosity=2)
