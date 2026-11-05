"""Authenticated loopback HTTP transport with isolated Controller SQLite.

Validates HTTP JSON, Agent authentication, pending state, terminal ACK and
replay without installing or starting Minecraft. No external port is opened.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading
import unittest
from urllib.request import Request, urlopen
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"database",ROOT/"dashboard",ROOT/"core"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))

from tests.agent_instance_provisioning_test import ControllerProvisioningQueueTest
from agent_remote_http import dispatch_heartbeat

class HttpFinalizationE2E(ControllerProvisioningQueueTest):
    def setUp(self):
        super().setUp()
        backend=self.backend
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length=int(self.headers.get("Content-Length","0"))
                if length > 128_000:
                    self.send_error(413);return
                payload=json.loads(self.rfile.read(length))
                status,reply=dispatch_heartbeat(payload,headers=self.headers,backend=backend)
                blob=json.dumps(reply).encode()
                self.send_response(status)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
            def log_message(self,*_):pass
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join,1)
        self.addCleanup(self.server.shutdown)

    def heartbeat(self, result=None, *, headers=None):
        payload={"agent_id":"agent-b10"}
        if result is not None:payload["provisioning_result"]=result
        data=json.dumps(payload).encode()
        request=Request(
            f"http://127.0.0.1:{self.server.server_port}/api/agent/heartbeat",
            data=data,method="POST",headers={
                **(self.headers if headers is None else headers),
                "Content-Type":"application/json",
            })
        with urlopen(request,timeout=15) as response:
            return response.status,json.loads(response.read())

    def create_job(self):
        return self.jobs.enqueue(
            agent_id="agent-b10", instance_id="instance-b10",
            environment_id="minecraft.java.neoforge",
            selector="26.1.2@26.1.2.109",
            selection={"game":"minecraft","version":"26.1.2","build":"26.1.2.109"},
            desired_state="running",
        )

    def test_pending_then_completed_and_duplicate_ack_over_http(self):
        created=self.create_job()
        pid=created["provisioning_id"]
        status,delivered=self.heartbeat()
        self.assertEqual(status,200)
        self.assertEqual(delivered["provisioning_command"]["provisioning_id"],pid)
        evidence={
            "status":"finalization_pending",
            "trace":["committed","finalization_pending"],
            "migration_plan_sha256":"a"*64,
        }
        pending={
            "provisioning_id":pid,"instance_id":"instance-b10","status":"running",
            "progress":99,"current_step":"minecraft_serverpack_finalization",
            "finalization_state":"pending",
            "minecraft_serverpack_migration":evidence,
        }
        status,first=self.heartbeat(pending)
        self.assertEqual(status,200)
        self.assertEqual(first["provisioning_state"]["status"],"running")
        self.assertEqual(first["provisioning_state"]["progress"],99)
        self.assertEqual(self.jobs.snapshot(pid)["status"],"running")
        complete={
            **pending,"status":"completed","progress":100,
            "current_step":"completed","finalization_state":"completed",
            "minecraft_serverpack_migration":{
                **evidence,"status":"completed","trace":["committed","finalized"],
                "finalization":{"status":"archived","sha256":"b"*64},
            },
        }
        status,ack=self.heartbeat(complete)
        self.assertEqual(status,200)
        self.assertEqual(ack["provisioning_state"]["status"],"completed")
        self.assertEqual(self.jobs.snapshot(pid)["progress"],100)
        status,replay=self.heartbeat(complete)
        self.assertEqual(status,200)
        self.assertEqual(replay["provisioning_state"]["status"],"completed")
        status,stale=self.heartbeat(pending)
        self.assertEqual(status,200)
        self.assertEqual(stale["provisioning_state"]["status"],"completed")

    def test_wrong_agent_credentials_refused_over_http(self):
        from urllib.error import HTTPError
        created=self.create_job()
        with self.assertRaises(HTTPError) as error:
            self.heartbeat(headers={**self.headers,"X-Capivara-Agent-Secret":"invalid-secret"})
        self.assertEqual(error.exception.code,401)
        self.assertEqual(self.jobs.snapshot(created["provisioning_id"])["status"],"queued")

    def test_premature_http_success_rejected_without_terminal_publication(self):
        created=self.create_job()
        pid=created["provisioning_id"]
        self.heartbeat()
        bad={
            "provisioning_id":pid,"instance_id":"instance-b10",
            "status":"completed","progress":100,
            "minecraft_serverpack_migration":{
                "status":"finalization_pending","trace":["committed","finalization_pending"]},
        }
        # The heartbeat endpoint intentionally preserves Agent connectivity
        # while surfacing a failed provisioning exchange as unavailable.
        status,reply=self.heartbeat(bad)
        self.assertEqual(status,200)
        self.assertEqual(reply["provisioning_state"]["status"],"unavailable")
        self.assertNotEqual(self.jobs.snapshot(pid)["status"],"completed")

if __name__=="__main__":unittest.main()
