"""Serve the REAL customer HTML/JS and authenticated Controller content read model.

Disposable GitHub-hosted browser acceptance fixture: real SQLite revision 3
with 291 managed mods/493 local states, but no installed DSM/game instance.
The boot-witness health gate intentionally remains blocked.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
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
        # A second browser acceptance case tests the positive read-model
        # projection with an injected, strictly disposable authenticated Agent
        # witness. It does NOT claim a real JVM boot in this browser fixture.
        health_ready=os.environ.get('DSM_1013_BROWSER_HEALTH_READY')=='1'
        fixture_control_token=secrets.token_urlsafe(24)
        health_state={'running':health_ready}
        if health_ready:
            assert os.environ.get('DSM_SERVERPACK_HEALTH_PROMOTION_ENABLED')=='1'
            from content_repository import ContentRepository
            from agent_heartbeat_api import record_agent_heartbeat
            from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
            current=ContentRepository(fixture.backend)._bundle_row(fixture.iid,'atm11')
            assert current and int(current['revision'])==3
            with fixture.backend.connect() as connection:
                rows=connection.execute(
                    "SELECT port FROM instance_ports WHERE instance_id=? AND name='game' AND protocol='tcp'",
                    (fixture.iid,)).fetchall()
            assert len(rows)==1
            game_port=int(rows[0]['port'])
            now=datetime.now(timezone.utc)
            start,done=now-timedelta(minutes=3),now-timedelta(minutes=1)
            boot={'status':'boot_process_observed',
                  'reason':'current_java_and_done_log_bound',
                  'proof_scope':'advisory_current_process_log',
                  'java_pid':41234,'java_started_at':start.isoformat(),
                  'done_at':done.isoformat(),
                  'boot_verified':False,'ready_for_release':False}
            operational={'status':'functional_boot_attested',
                         'proof_scope':'owned_jvm_and_live_minecraft_status',
                         'instance_id':fixture.iid,'bundle_revision':int(current['revision']),
                         'manifest_sha256':current['manifest_sha256'],
                         'game_port':game_port,'java_pid':41234,
                         'java_started_at':start.isoformat(),
                         'done_at':done.isoformat(),
                         'boot_verified':True,'ready_for_release':False}
            health={'instance_id':fixture.iid,'desired_state':'running',
                    'observed_state':'running','reconcile_status':'healthy',
                    'health':'healthy','operation_status':'idle',
                    'generated_at':now.isoformat()}
            response=record_agent_heartbeat(fixture.agent,{
                'agent_id':fixture.agent,'instance_runtime_health':[health],
                'minecraft_serverpack_observations':{
                    'observed_at':now.isoformat(),
                    'observations':[{
                        'instance_id':fixture.iid,'content_id':'atm11',
                        'bundle_revision':int(current['revision']),
                        'manifest_sha256':current['manifest_sha256'],
                        'status':'physical_runtime_verified',
                        'reason':'boot_not_observed',
                        'boot_verified':False,'ready_for_release':False,
                        'boot_observation':boot,
                        'operational_attestation':operational,
                    }],
                },
            },backend=fixture.backend)
            assert response['serverpack_observations_created']==1
            status,confirmed=fixture.fetch(fixture.customer_token)
            assert status==200 and confirmed['content'][0]['bundle_summary']['health_gate']=='ready'
        else:
            from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
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
                                    "game_id":"minecraft","status":"running" if health_state['running'] else "stopped"},
                        "runtime":{"state":"running" if health_state['running'] else "stopped",
                                   "health":"healthy" if health_state['running'] else "degraded"},
                        "content_sections":["modpacks"],
                        "runtime_capabilities":{"modpacks":True,"providers":{"modpack":[]}},
                        "content_policy":{"external_upload_allowed":False},
                        "telemetry":{},"ports":[],"storage":{},"policy":{},
                    })
                if path=="/api/customer/instance/workspace/telemetry":
                    return self.send_json(200,{"samples":[]})
                return super().do_GET()
            def do_POST(self):
                if urlparse(self.path).path=='/__dsm_fixture__/revoke':
                    if (not health_ready or self.client_address[0]!='127.0.0.1'
                            or self.headers.get('X-DSM-Fixture-Control')!=fixture_control_token):
                        return self.send_json(403,{'error':'forbidden'})
                    AgentInstanceRuntimeHealthRepository(fixture.backend).apply_inventory(
                        fixture.agent,[{'instance_id':fixture.iid,
                                        'desired_state':'running','observed_state':'stopped',
                                        'reconcile_status':'degraded','health':'degraded',
                                        'operation_status':'idle',
                                        'generated_at':datetime.now(timezone.utc).isoformat()}])
                    health_state['running']=False
                    return self.send_json(200,{'status':'revoked'})
                return super().do_POST()
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
            "health_gate":"ready" if health_ready else "blocked",
            "fixture_control_token":fixture_control_token,
            "evidence_scope":"injected_disposable_agent_witness" if health_ready else "no_boot_witness",
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
