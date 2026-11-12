"""Authenticated Chromium acceptance over the SAME real-JVM Controller SQLite.

Only invoked by the explicit GitHub-hosted official ATM11 systemd fixture. The
browser reads authoritative temporary ContentRepository state and causes a
controlled shutdown of that very JVM; no synthetic boot evidence is admitted.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]

import controller_session
import customer_content_http

_WEB=ROOT/'dashboard/web'
_ASSETS={
    'customer-instance.html','customer-instance-v2.js',
    'customer-instance-v2.css','customer-instance-runtime-live.js',
    'customer-maintenance.js','customer-content-update-policy.js',
    'customer-profile.js','customer-backup-transfer.js',
    'customer-instance-activity.js','customer-instance-delete.js',
    'customer-dayz.js',
}


def verify_real_browser(fixture, *, instance_id:str, agent_id:str, root:Path,
                        stop_and_revoke, expected_mods:int=291,
                        expected_removed:int=1)->dict:
    """Launch actual Chromium and authenticated HTTP against the live JVM DB.

    stop_and_revoke must stop the *owned real JVM* then publish fresh negative
    agent runtime evidence; it is not a fake health toggle.
    """
    if (os.environ.get('CAPIVARA_RUN_1013_BROWSER_E2E')!='1'
        or os.environ.get('DSM_1013_BROWSER_REAL_JVM')!='1'
        or os.environ.get('GITHUB_ACTIONS')!='true'
        or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted'
        or os.environ.get('DSM_SERVERPACK_HEALTH_PROMOTION_ENABLED')!='1'
        or Path('/opt/dsm/runtime/hybrid-instance-storage').exists()):
        raise RuntimeError('refuse real JVM/browser test outside opted-in disposable runner')
    token=secrets.token_urlsafe(24)
    session_file=root/'dsm1013-browser-session.json'
    ready_file=root/'dsm1013-real-browser-ready.json'
    screenshot=root/'dsm1013-real-browser.png'
    health={'running':True}
    backend=fixture.backend
    with patch.object(controller_session,'SESSION_FILE',session_file):
        with controller_session._lock:
            controller_session._sessions.clear()
            controller_session._loaded=False
        with backend.transaction() as con:
            con.execute(
                'INSERT INTO dashboard_users (username,password_hash,role,scope_id,active) '
                'VALUES (?,?,?,?,?)',
                ('dsm1013-real-jvm-browser','not-a-login-credential',
                 'customer','isolated',1))
            con.execute(
                'INSERT INTO instance_access (username,instance_id,permission_profile) '
                'VALUES (?,?,?)',
                ('dsm1013-real-jvm-browser',instance_id,'manager'))
        customer_token=controller_session.create_session({
            'username':'dsm1013-real-jvm-browser','role':'customer',
            'scope_id':'isolated','customer_id':1,
        },area='customer')
        admin_token=controller_session.create_session({
            'username':'dsm1013-disposable-admin','role':'admin',
            'scope_id':'isolated',
        },area='controller')
        class RawHandler(BaseHTTPRequestHandler):
            def send_json(self,status,body):
                data=json.dumps(body,default=str).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)))
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                self.wfile.write(data)
            def log_message(self,*_args):pass
            def unauthorized(self):self.send_json(401,{'error':'unauthorized'})
            def forbidden(self):self.send_json(403,{'error':'forbidden'})
            def read_json_body(self):
                return json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
            def do_GET(self):self.send_json(404,{'error':'not_found'})
            def do_POST(self):self.send_json(404,{'error':'not_found'})
        gateway=SimpleNamespace(
            DashboardHandler=RawHandler,DSM_ROOT=ROOT,DATABASE_FILE='unused',
            dashboard_repository=lambda _path:SimpleNamespace(backend=backend),
        )
        customer_content_http.install_customer_content_http(
            gateway,authenticate=lambda _headers:None)
        class BrowserHandler(gateway.DashboardHandler):
            def do_GET(self):
                path=urlparse(self.path).path
                name=path.lstrip('/')
                if name in _ASSETS:
                    asset=_WEB/name
                    if not asset.is_file():
                        return self.send_json(404,{'error':'not_found'})
                    data=asset.read_bytes()
                    kind=('text/html' if name.endswith('.html') else
                          'text/css' if name.endswith('.css') else
                          'application/javascript')
                    self.send_response(200)
                    self.send_header('Content-Type',kind+'; charset=utf-8')
                    self.send_header('Content-Length',str(len(data)))
                    self.send_header('Cache-Control','no-store')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if path=='/api/customer/instance/workspace':
                    return self.send_json(200,{
                        'permissions':['content.read'],
                        'instance':{'id':instance_id,'game_id':'minecraft',
                                    'name':'ATM11 systemd real JVM disposable',
                                    'status':'running' if health['running'] else 'stopped'},
                        'runtime':{'state':'running' if health['running'] else 'stopped',
                                   'health':'healthy' if health['running'] else 'degraded'},
                        'content_sections':['modpacks'],
                        'runtime_capabilities':{'modpacks':True,'providers':{'modpack':[]}},
                        'content_policy':{'external_upload_allowed':False},
                        'telemetry':{},'ports':[],'storage':{},'policy':{},
                    })
                if path=='/api/customer/instance/workspace/telemetry':
                    return self.send_json(200,{'samples':[]})
                return super().do_GET()
            def do_POST(self):
                if urlparse(self.path).path!='/__dsm_fixture__/revoke':
                    return super().do_POST()
                if (self.client_address[0]!='127.0.0.1'
                    or self.headers.get('X-DSM-Fixture-Control')!=token
                    or not health['running']):
                    return self.send_json(403,{'error':'forbidden'})
                try:
                    stop_and_revoke()
                except Exception as exc:
                    return self.send_json(500,{'error':'jvm_revocation_failed',
                                               'type':type(exc).__name__})
                health['running']=False
                return self.send_json(200,{'status':'real_jvm_stopped_and_revoked'})
        server=ThreadingHTTPServer(('127.0.0.1',0),BrowserHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            ready_file.write_text(json.dumps({
                'base_url':f'http://127.0.0.1:{server.server_port}',
                'instance_id':instance_id,'customer_token':customer_token,
                'controller_token':admin_token,'expected_mods':expected_mods,
                'expected_absent':expected_removed,'health_gate':'ready',
                'fixture_control_token':token,
                'evidence_scope':'owned_real_jvm_same_controller',
            }))
            ready_file.chmod(0o600)
            env={**os.environ,
                 'CAPIVARA_RUN_1013_BROWSER_E2E':'1',
                 'DSM_1013_BROWSER_HEALTH_READY':'1',
                 'DSM_1013_BROWSER_REAL_JVM':'1',
                 'DSM_1013_BROWSER_READY_FILE':str(ready_file),
                 'DSM_1013_BROWSER_SCREENSHOT':str(screenshot)}
            proc=subprocess.run([
                'node',str(ROOT/'tests/minecraft_serverpack_customer_real_browser_e2e.test.js')],
                cwd=ROOT,env=env,timeout=160,check=True,
            )
            assert proc.returncode==0 and screenshot.is_file()
            assert (root/'dsm1013-real-browser-ready.png').is_file()
            assert health['running'] is False,'browser failed to stop real JVM'
            print('DSM1013_REAL_JVM_AUTHENTICATED_BROWSER_PASS',json.dumps({
                'session':'customer_cookie','controller':'same_disposable_sqlite',
                'jvm':'same_owned_real_systemd_process',
                'health_gate':'ready_then_blocked',
                'production_touched':False,
            }),flush=True)
            return {'real_browser_same_jvm':True,'health_gate':'ready_then_blocked'}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            ready_file.unlink(missing_ok=True)
            session_file.unlink(missing_ok=True)
            with controller_session._lock:
                controller_session._sessions.clear()
                controller_session._loaded=False
