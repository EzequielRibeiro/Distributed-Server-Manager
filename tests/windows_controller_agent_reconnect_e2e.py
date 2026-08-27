#!/usr/bin/env python3
"""Native Windows P4 gate: HTTPS enrollment, outage, health transition, queue and reconnect."""
from __future__ import annotations

import importlib
import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for directory in (ROOT,ROOT/"database",ROOT/"dashboard",ROOT/"agents"/"windows"/"runtime"):
    if str(directory) not in sys.path: sys.path.insert(0,str(directory))
from backend import DatabaseConfig
from backend_factory import create_backend
from agent_admin_repository import AgentAdminRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll,dispatch_heartbeat
from agent_runtime_repository import AgentRuntimeRepository

class ReusableServer(ThreadingHTTPServer): allow_reuse_address=True
class Handler(BaseHTTPRequestHandler):
    backend=None
    def log_message(self,*args): return
    def _reply(self,status,payload):
        body=json.dumps(payload,default=str).encode();self.send_response(status);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self): self._reply(200,{"status":"ok"}) if self.path=="/ping" else self._reply(404,{"error":"not_found"})
    def do_POST(self):
        length=int(self.headers.get("Content-Length") or 0);payload=json.loads(self.rfile.read(length).decode() if length else "{}")
        if self.path=="/api/agent/enroll": status,result=dispatch_enroll(payload,backend=self.backend)
        elif self.path=="/api/agent/heartbeat": status,result=dispatch_heartbeat(payload,headers=self.headers,backend=self.backend)
        else: status,result=404,{"error":"not_found"}
        self._reply(status,result)

def cert_pair(root:Path):
    cert=root/"controller.crt";key=root/"controller.key"
    subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes","-sha256","-days","1","-subj","/CN=localhost","-addext","subjectAltName=DNS:localhost","-keyout",str(key),"-out",str(cert)],check=True,capture_output=True)
    return cert,key

def start_server(port:int,backend,cert:Path,key:Path):
    Handler.backend=backend;server=ReusableServer(("127.0.0.1",port),Handler);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2;ctx.load_cert_chain(str(cert),str(key));server.socket=ctx.wrap_socket(server.socket,server_side=True);threading.Thread(target=server.serve_forever,daemon=True).start();return server

def parse_time(value): return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)

def main()->int:
    if os.name!="nt": raise SystemExit("Windows P4 E2E must run on Windows")
    with tempfile.TemporaryDirectory(prefix="capivara-p4-win-") as temp:
        root=Path(temp);state=root/"state";config_path=root/"agent.json";os.environ["CAPIVARA_AGENT_STATE_DIR"]=str(state);os.environ["CAPIVARA_AGENT_CONFIG"]=str(config_path);cert,key=cert_pair(root);os.environ["SSL_CERT_FILE"]=str(cert)
        db=root/"capivara.db";backend=create_backend(DatabaseConfig(driver="sqlite",database=str(db)));backend.initialize()
        with sqlite3.connect(db) as c:
            c.execute("INSERT INTO nodes(id,name,role,status,metadata_json) VALUES (?,?,?,?,?)",("controller-p4-win-node","P4 Windows Controller","controller","active","{}"));c.execute("INSERT INTO controllers(id,node_id,name,status,metadata_json) VALUES (?,?,?,?,?)",("controller-p4-win","controller-p4-win-node","P4 Windows Controller","active","{}"));c.commit()
        pairing=AgentPairingRepository(backend).issue_token(controller_id="controller-p4-win")
        with socket.socket() as s: s.bind(("127.0.0.1",0));port=s.getsockname()[1]
        config={"agent_id":"agent-p4-windows","node_id":"node-p4-windows","name":"P4 Windows Agent","hostname":"p4-windows","fingerprint":"sha256:p4-windows","controller_url":f"https://localhost:{port}","pairing_token":pairing.token,"capivara_version":"2.0.9-p4","heartbeat_interval_seconds":1,"degraded_after_seconds":2,"offline_after_seconds":4}
        config_path.write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")
        win_agent=importlib.import_module("agent");server=start_server(port,backend,cert,key)
        try:
            started=time.perf_counter();enrolled=win_agent.enroll(win_agent._load_config());enroll_rtt=round((time.perf_counter()-started)*1000,3);assert enrolled.get("credential_id") and not enrolled.get("pairing_token")
            started=time.perf_counter();first=win_agent.heartbeat(enrolled);first_rtt=round((time.perf_counter()-started)*1000,3);assert first.get("health_status")=="online"
            repo=AgentRuntimeRepository(backend);snap=repo.snapshot("agent-p4-windows",refresh_health=False);last_seen=parse_time(snap["last_seen"])
            server.shutdown();server.server_close();server=None
            failed=False
            try: win_agent.heartbeat(enrolled)
            except RuntimeError: failed=True
            assert failed
            assert repo.refresh_health(now=last_seen+timedelta(seconds=3))["agent-p4-windows"]=="degraded"
            assert repo.refresh_health(now=last_seen+timedelta(seconds=5))["agent-p4-windows"]=="offline"
            admin=AgentAdminRepository(backend);queued=admin.request_doctor("agent-p4-windows",requested_by="p4:windows-e2e");assert str(queued.get("status") or "").lower()=="queued"
            server=start_server(port,backend,cert,key);started=time.perf_counter();delivery=win_agent.heartbeat(enrolled);reconnect_rtt=round((time.perf_counter()-started)*1000,3);assert delivery.get("doctor_command") or str((delivery.get("doctor_state") or {}).get("status") or "").lower() in {"queued","running"}
            win_agent.heartbeat(enrolled);latest=admin.latest_doctor("agent-p4-windows");assert str((latest or {}).get("status") or "").lower()=="completed";assert repo.snapshot("agent-p4-windows")["health_status"]=="online"
            print(json.dumps({"status":"passed","platform":"windows","transport":"https","hostname_validation":"localhost","enroll_rtt_ms":enroll_rtt,"heartbeat_rtt_ms":first_rtt,"reconnect_rtt_ms":reconnect_rtt,"health_transition":["online","degraded","offline","online"],"queued_while_offline":True,"doctor_completed_after_reconnect":True},indent=2));return 0
        finally:
            if server is not None: server.shutdown();server.server_close()
            backend.close()

if __name__=="__main__": raise SystemExit(main())
