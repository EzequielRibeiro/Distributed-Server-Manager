#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/"dashboard",ROOT/"database",ROOT/"core"):
    if str(path) not in sys.path:
        sys.path.insert(0,str(path))

import customer_content_http as http_layer


class MigrationEnqueueHTTPTest(unittest.TestCase):
    def _server(self,service_factory):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def send_json(self,status,payload):
                blob=json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
            def read_json_body(self):
                length=int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length).decode("utf-8"))
            def unauthorized(self):
                self.send_json(401,{"error":"unauthorized"})
            def forbidden(self):
                self.send_json(403,{"error":"forbidden"})
            def do_GET(self):
                self.send_json(404,{"error":"not_found"})
            def do_POST(self):
                self.send_json(404,{"error":"not_found"})
        legacy=SimpleNamespace(
            DashboardHandler=Handler,
            DSM_ROOT=ROOT,
            DATABASE_FILE="unused",
            dashboard_repository=lambda _:SimpleNamespace(backend=object()),
        )
        http_layer.install_customer_content_http(
            legacy,
            lambda headers:{"role":"customer","username":"alice","customer_id":1},
        )
        server=ThreadingHTTPServer(("127.0.0.1",0),legacy.DashboardHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        patcher=patch.object(
            http_layer,
            "MinecraftServerPackMigrationService",
            service_factory(calls),
        )
        patcher.start();thread.start()
        return server,thread,patcher,calls

    def test_enqueue_route_preserves_exact_fingerprint_and_returns_202(self):
        class Factory:
            def __init__(self,calls):
                self.calls=calls
            def __call__(self,backend,root):
                calls=self.calls
                class Service:
                    def request(self,user,transfer_id,body,fingerprint):
                        calls.append({
                            "user":dict(user),
                            "transfer_id":transfer_id,
                            "body":dict(body),
                            "fingerprint":fingerprint,
                        })
                        return {
                            "accepted":True,
                            "homologation_only":True,
                            "provisioning_id":"instance-provision-pr855-http",
                            "status":"queued",
                            "migration":{
                                "migration_plan_sha256":fingerprint,
                            },
                            "pending_bundle":{
                                "publish_allowed":False,
                            },
                        }
                return Service()
        server,thread,patcher,calls=self._server(Factory)
        try:
            payload={
                "instance_id":"pr855-http",
                "transfer_id":"transfer-http",
                "content_id":"atm11",
                "content_type":"modpack",
                "metadata":{"serverpack":{"format":"official-serverpack-v1"}},
                "migration_plan_sha256":"b"*64,
                # These must not be forwarded into the read-only preview body.
                "install_allowed":True,
                "unexpected":"ignored",
            }
            req=urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}"+
                "/api/customer/instance/workspace/content/upload/migration/enqueue",
                method="POST",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type":"application/json"},
            )
            with urllib.request.urlopen(req,timeout=3) as response:
                body=json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status,202)
            self.assertTrue(body["migration"]["accepted"])
            self.assertFalse(body["migration"]["pending_bundle"]["publish_allowed"])
            self.assertEqual(len(calls),1)
            call=calls[0]
            self.assertEqual(call["transfer_id"],"transfer-http")
            self.assertEqual(call["fingerprint"],"b"*64)
            self.assertEqual(
                set(call["body"]),
                {"instance_id","transfer_id","content_id","content_type","metadata"},
            )
            self.assertNotIn("migration_plan_sha256",call["body"])
            self.assertNotIn("install_allowed",call["body"])
            self.assertNotIn("unexpected",call["body"])
        finally:
            patcher.stop();server.shutdown();server.server_close();thread.join(timeout=5)

    def test_blocked_homologation_is_a_safe_client_error_not_500(self):
        class Factory:
            def __init__(self,calls):
                self.calls=calls
            def __call__(self,backend,root):
                class Service:
                    def request(self,user,transfer_id,body,fingerprint):
                        raise ValueError(
                            "Server Pack migration provisioning remains restricted to PR855 homologation"
                        )
                return Service()
        server,thread,patcher,calls=self._server(Factory)
        try:
            payload={
                "instance_id":"cli-000001-minecraft-005",
                "transfer_id":"transfer-prod",
                "content_id":"atm11",
                "content_type":"modpack",
                "metadata":{},
                "migration_plan_sha256":"b"*64,
            }
            req=urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}"+
                "/api/customer/instance/workspace/content/upload/migration/enqueue",
                method="POST",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type":"application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(req,timeout=3)
            self.assertEqual(denied.exception.code,400)
            body=json.loads(denied.exception.read().decode("utf-8"))
            self.assertEqual(body["error"],"invalid_request")
            self.assertIn("restricted to PR855 homologation",body["message"])
        finally:
            patcher.stop();server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=="__main__":
    unittest.main()
