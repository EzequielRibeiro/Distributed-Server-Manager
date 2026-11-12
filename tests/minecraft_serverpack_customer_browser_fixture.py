"""Serve the REAL customer HTML/JS and authenticated Controller content read model.

Disposable GitHub-hosted browser acceptance fixture: real SQLite revision 3
with 291 managed mods/493 local states, but no installed DSM/game instance.
The boot-witness health gate intentionally remains blocked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
for directory in (ROOT,ROOT/"tests",ROOT/"database",ROOT/"core",ROOT/"dashboard",
                  ROOT/"agents/linux/runtime",ROOT/"agents/common"):
    if str(directory) not in sys.path:
        sys.path.insert(0,str(directory))

from tests.minecraft_serverpack_customer_session_readmodel_e2e_test import (
    CustomerSessionReadmodelE2E,
)
from tests.minecraft_serverpack_customer_single_action_e2e_test import (
    SingleCustomerActionToAuthenticatedAckE2E,
)

def serve(ready_file:Path)->None:
    if not (os.environ.get("GITHUB_ACTIONS")=="true" and
            os.environ.get("RUNNER_ENVIRONMENT")=="github-hosted" and
            os.environ.get("CAPIVARA_RUN_1013_BROWSER_E2E")=="1"):
        raise RuntimeError("browser fixture requires opt-in disposable hosted CI")
    if Path("/opt/dsm/runtime/hybrid-instance-storage").exists():
        raise RuntimeError("installed DSM detected: browser fixture forbidden")
    fixture=CustomerSessionReadmodelE2E(
        methodName="test_authenticated_customer_reads_blocked_until_current_runtime_witness")
    fixture.setUp()
    try:
        SingleCustomerActionToAuthenticatedAckE2E.test_one_action_to_physical_swap_controller_cas_authenticated_ack(fixture)
        code,response=fixture.fetch(fixture.customer_token)
        assert code==200 and len(response["content"])==1
        item=response["content"][0]
        assert item["bundle_summary"]["health_gate"]=="blocked"
        assert item["bundle_summary"]["current_boot_witness"]=="missing"
        assert item["bundle_summary"]["physical_attestation"]=="verified"
        assert item["bundle_summary"]["child_count"]==291
        assert item["bundle_summary"]["absent_child_count"]==201
        real_handler=fixture.customer_server.RequestHandlerClass
        webroot=ROOT/"dashboard/web"
        allowed_assets={
            "customer-instance.html",
            "customer-instance-v2.js",
            "customer-instance-v2.css",
            "customer-instance-runtime-live.js",
            "customer-maintenance.js",
            "customer-content-update-policy.js",
            "customer-profile.js",
            "customer-backup-transfer.js",
            "customer-instance-activity.js",
            "customer-instance-delete.js",
            "customer-dayz.js",
        }
        class BrowserHandler(real_handler):
            def do_GET(self):
                path=urlparse(self.path).path
                name=path.lstrip("/")
                if name in allowed_assets:
                    asset=webroot/name
                    if not asset.is_file():
                        return self.send_json(404,{"error":"not_found"})
                    data=asset.read_bytes()
                    kind=("text/html" if name.endswith(".html") else
                          "text/css" if name.endswith(".css") else
                          "application/javascript")
                    self.send_response(200)
                    self.send_header("Content-Type",kind+"; charset=utf-8")
                    self.send_header("Content-Length",str(len(data)))
                    self.send_header("Cache-Control","no-store")
                    self.send_header("X-Content-Type-Options","nosniff")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if path=="/api/customer/instance/workspace":
                    return self.send_json(200,{
                        "permissions":["content.read"],
                        "instance":{"id":fixture.iid,"name":"ATM11 homologacao descartavel",
                                    "game_id":"minecraft","status":"stopped"},
                        "runtime":{"state":"stopped","health":"degraded"},
                        "content_sections":["modpacks"],
                        "runtime_capabilities":{"modpacks":True,"providers":{"modpack":[]}},
                        "content_policy":{"external_upload_allowed":False},
                        "telemetry":{},"ports":[],"storage":{},"policy":{},
                    })
                if path=="/api/customer/instance/workspace/telemetry":
                    return self.send_json(200,{"samples":[]})
                return super().do_GET()
        fixture.customer_server.RequestHandlerClass=BrowserHandler
        ready_file.parent.mkdir(parents=True,exist_ok=True)
        assert not ready_file.exists()
        ready_file.write_text(json.dumps({
            "base_url":f"http://127.0.0.1:{fixture.customer_server.server_port}",
            "instance_id":fixture.iid,
            "customer_token":fixture.customer_token,
            "controller_token":fixture.controller_token,
            "expected_mods":291,
            "expected_absent":201,
            "health_gate":"blocked",
        }))
        ready_file.chmod(0o600)
        print("DSM1013_BROWSER_FIXTURE_READY",flush=True)
        stopped=False
        def stop(_signum,_frame):
            nonlocal stopped
            stopped=True
        signal.signal(signal.SIGTERM,stop)
        signal.signal(signal.SIGINT,stop)
        while not stopped:
            time.sleep(0.2)
    finally:
        ready_file.unlink(missing_ok=True)
        fixture.doCleanups()

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("usage: python browser_fixture.py /path/to/ready.json")
    serve(Path(sys.argv[1]))
