"""Two real transient systemd services: Controller HTTP and Linux Agent transfer.

Opt-in exclusively on a disposable GitHub-hosted runner. Temporary SQLite,
spool, Agent quarantine, credentials and loopback listeners; no installed DSM.
This tests process and service separation with a small synthetic ZIP. The 751
MiB official ZIP is covered by the separate real-upload/boot workflow.
"""
from __future__ import annotations
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
for folder in (ROOT,ROOT/"tests",ROOT/"database",ROOT/"dashboard",
               ROOT/"core",ROOT/"agents/linux/runtime",ROOT/"agents/common"):
    if str(folder) not in sys.path:sys.path.insert(0,str(folder))

def _backend(path):
    from backend import DatabaseConfig
    from backend_factory import create_backend
    return create_backend(DatabaseConfig(driver="sqlite",database=str(path)))

def _controller(config):
    from artifact_transfer_http import install_artifact_transfer_http
    from agent_remote_http import dispatch_heartbeat
    backend=_backend(config["database"])
    root=Path(config["controller_root"])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def send_json(self,status,payload):
            data=json.dumps(payload,default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def unauthorized(self):self.send_json(401,{"error":"unauthorized"})
        def do_GET(self):
            if self.path=="/_dsm1013_ready":
                return self.send_json(200,{"ready":True})
            self.send_json(404,{"error":"not_found"})
        def do_POST(self):
            if self.path!="/api/agent/heartbeat":
                return self.send_json(404,{"error":"not_found"})
            body=json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            status,result=dispatch_heartbeat(body,headers=self.headers,backend=backend)
            self.send_json(status,result)
    legacy=SimpleNamespace(DashboardHandler=Handler,DSM_ROOT=root,
        DATABASE_FILE=str(config["database"]),
        dashboard_repository=lambda _p:SimpleNamespace(backend=backend))
    install_artifact_transfer_http(legacy,lambda _headers:None)
    server=ThreadingHTTPServer(("127.0.0.1",int(config["port"])),legacy.DashboardHandler)
    try:
        print("DSM1013_TRANSIENT_CONTROLLER_READY",flush=True)
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        backend.close()

def _agent(config):
    import artifact_transfer_client as client
    command=config["command"]
    conn_host="127.0.0.1"
    conn_port=int(config["port"])
    auth={"X-Capivara-Agent-Credential":config["credential_id"],
          "X-Capivara-Agent-Secret":config["credential_secret"],
          "X-Capivara-Agent-Fingerprint":config["fingerprint"]}
    params={"controller_url":f"http://{conn_host}:{conn_port}",
            "credential_id":config["credential_id"],
            "credential_secret":config["credential_secret"],
            "fingerprint":config["fingerprint"]}
    report=client.handle_command(params,command)
    if report["status"]!="completed":
        raise AssertionError("Agent download failed: "+repr(report))
    conn=http.client.HTTPConnection(conn_host,conn_port,timeout=30)
    payload=json.dumps({"agent_id":config["agent_id"],
                        "artifact_result":report,"result_flush":True}).encode("utf-8")
    conn.request("POST","/api/agent/heartbeat",body=payload,
                 headers={**auth,"Content-Type":"application/json"})
    reply=conn.getresponse()
    result=json.loads(reply.read())
    status=reply.status
    conn.close()
    if status!=200:raise AssertionError((status,result))
    if result.get("artifact_state",{}).get("status")!="completed":
        raise AssertionError("not durably ACKed by Controller heartbeat: "+repr(result))
    output={"heartbeat_http_status":status,"artifact_state":result["artifact_state"],
            "download_report":report,"agent_pid":os.getpid()}
    Path(config["result_file"]).write_text(json.dumps(output,sort_keys=True))
    print("DSM1013_TRANSIENT_AGENT_HEARTBEAT_ACK_PASS",flush=True)

@unittest.skipUnless(
    os.environ.get("CAPIVARA_RUN_SYSTEMD_FINALIZATION_E2E")=="1"
    and os.environ.get("GITHUB_ACTIONS")=="true"
    and os.environ.get("RUNNER_ENVIRONMENT")=="github-hosted"
    and hasattr(os,"geteuid") and os.geteuid()==0,
    "isolated 2-unit systemd integration runs only on opted-in hosted CI as root",
)
class TwoDisposableSystemdServicesE2E(unittest.TestCase):
    def setUp(self):
        self.assertTrue(shutil.which("systemd-run"))
        self.assertTrue(Path("/run/systemd/system").is_dir())
        self.assertFalse(Path("/opt/dsm/runtime/hybrid-instance-storage").exists())
        self.tmp=tempfile.TemporaryDirectory(prefix="dsm-1013-2services-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.controller_root=self.root/"controller"
        self.controller_root.mkdir()
        self.database=self.root/"isolated.sqlite"
        self.backend=_backend(self.database)
        self.backend.initialize()
        self.addCleanup(self.backend.close)
        self.agent_id="pr839-isolated-agent"
        self.instance_id="pr855-isolated-two-services"
        self.cred_id="dsm1013-2services-cred"
        self.cred_secret="only-used-by-disposable-ci"
        self.fingerprint="dsm1013-2services-fingerprint"
        from core.agent_identity import secret_digest
        with self.backend.transaction() as db:
            db.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                       ("node-controller","DSM disposable","controller"))
            db.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                       ("node-agent","Agent disposable","agent"))
            db.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",
                       ("ctrl","node-controller","Controller fixture"))
            db.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                       (self.agent_id,"ctrl","node-agent","Agent fixture","active"))
            customer=db.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",
                                ("ctrl","Disposable customer"))
            db.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (self.instance_id,"node-agent","minecraft","Scratch","stopped",
                        "ctrl",self.agent_id,customer.lastrowid))
            db.execute("INSERT INTO agent_credentials "
                "(id,agent_id,controller_id,credential_type,secret_hash,fingerprint,status)"
                " VALUES (?,?,?,?,?,?,?)",
                (self.cred_id,self.agent_id,"ctrl","opaque-v1",
                 secret_digest(self.cred_secret),self.fingerprint,"active"))
        from artifact_transfer_repository import ArtifactTransferRepository
        self.repo=ArtifactTransferRepository(self.backend,self.controller_root)
        self.official=(os.environ.get("DSM_1013_SYSTEMD_OFFICIAL_ZIP")=="1")
        if self.official:
            source_root=Path(os.environ.get("DSM_1013_OFFICIAL_PACK_ROOT") or "")
            self.source=source_root/"ServerFiles-0.14.0-beta.zip"
            assert self.source.is_file(), "missing official ATM11 Server Pack"
        else:
            self.source=self.root/"tiny-isolated-serverpack.zip"
            with zipfile.ZipFile(self.source,"w") as archive:
                archive.writestr("mods/isolation.jar",b"safe-synthetic-fixture")
                archive.writestr("config/demo.toml",b"mock-server-mode=true")
        with self.source.open("rb") as f:
            self.digest=hashlib.file_digest(f,"sha256").hexdigest()
        if self.official:
            assert self.digest=="b8635562de0931eb5cadb51954c0fb78658033928ef54b5f73be6cae5c8897fa"
            assert self.source.stat().st_size==751264085
            with zipfile.ZipFile(self.source) as archive:
                mods=[i.filename for i in archive.infolist()
                      if i.filename.startswith("mods/") and i.filename.endswith(".jar")]
                assert len(mods)==291

        self.transfer=self.repo.create(agent_id=self.agent_id,
            instance_id=self.instance_id,direction="controller_to_agent",
            purpose="content_upload",filename=self.source.name,requested_by="ci")
        with self.source.open("rb") as f:
            self.repo.stage_from_controller(
                self.transfer["transfer_id"],f,self.source.stat().st_size)
        self.command=self.repo.command_for_agent(self.agent_id)
        self.assertIsNotNone(self.command)
        self.assertEqual(self.command["sha256"],self.digest)
        # Reserve a loopback port only for the duration of this tiny fixture.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            self.port=sock.getsockname()[1]
        self.config_file=self.root/"config.json"
        self.result_file=self.root/"agent-result.json"
        config={
            "database":str(self.database),"controller_root":str(self.controller_root),
            "port":self.port,"agent_id":self.agent_id,"instance_id":self.instance_id,
            "credential_id":self.cred_id,"credential_secret":self.cred_secret,
            "fingerprint":self.fingerprint,"command":self.command,
            "result_file":str(self.result_file),
        }
        self.config_file.write_text(json.dumps(config,sort_keys=True))
        suffix=uuid.uuid4().hex[:12]
        self.controller_unit="dsm-1013-ctrl-"+suffix+".service"
        self.agent_unit="dsm-1013-agent-"+suffix+".service"
        self.addCleanup(self._stop_all_units)
        self._start_controller()

    def _props(self):
        return ["--collect","--property=RuntimeMaxSec="+("300" if self.official else "90"),
                "--property=NoNewPrivileges=yes",
                "--property=MemoryMax="+("1536M" if self.official else "768M"),
                "--property=ProtectSystem=strict",
                "--property=ReadWritePaths="+str(self.root)]

    def _stop_all_units(self):
        for unit in (self.agent_unit,self.controller_unit):
            subprocess.run(["systemctl","stop",unit],capture_output=True,timeout=12)
            subprocess.run(["systemctl","reset-failed",unit],capture_output=True,timeout=12)

    def _start_controller(self):
        args=["systemd-run","--unit="+self.controller_unit,*self._props(),
              "--setenv=DSM_ROOT="+str(self.root),
              sys.executable,str(Path(__file__).resolve()),"controller",str(self.config_file)]
        started=subprocess.run(args,text=True,capture_output=True,timeout=20)
        self.assertEqual(started.returncode,0,started.stdout+started.stderr)
        deadline=time.monotonic()+18
        last=""
        while time.monotonic()<deadline:
            try:
                with urlopen("http://127.0.0.1:"+str(self.port)+"/_dsm1013_ready",
                             timeout=1) as response:
                    if response.status==200:return
            except Exception as exc:
                last=repr(exc)
            time.sleep(0.25)
        unit_log=subprocess.run(["journalctl","-u",self.controller_unit,"-n","30",
                                 "--no-pager"],capture_output=True,text=True,timeout=10)
        self.fail("transient Controller not ready: "+last+"\n"+unit_log.stdout)

    def test_separate_systemd_units_authenticated_agent_heartbeat_ack(self):
        download=("http://127.0.0.1:"+str(self.port)+
                  "/api/agent/artifacts/download?transfer_id="+
                  self.transfer["transfer_id"])
        with self.assertRaises(HTTPError) as denied:
            urlopen(download,timeout=5)
        self.assertEqual(denied.exception.code,401)
        env=[
            "--setenv=DSM_ROOT="+str(self.root),
            "--setenv=CAPIVARA_AGENT_STATE_DIR="+str(self.root/"agent-state"),
            "--setenv=CAPIVARA_GAME_DATA_ROOT="+str(self.root/"agent-game-data"),
            "--setenv=CAPIVARA_AGENT_GAME_DATA_ROOT="+str(self.root/"agent-game-data"),
        ]
        args=["systemd-run","--unit="+self.agent_unit,"--wait","--pipe",
              *self._props(),*env,sys.executable,str(Path(__file__).resolve()),
              "agent",str(self.config_file)]
        completed=subprocess.run(args,text=True,capture_output=True,
                                 timeout=260 if self.official else 60)
        self.assertEqual(completed.returncode,0,
                         completed.stdout+"\n"+completed.stderr)
        self.assertTrue(self.result_file.is_file())
        result=json.loads(self.result_file.read_text())
        self.assertEqual(result["heartbeat_http_status"],200)
        self.assertEqual(result["artifact_state"]["status"],"completed")
        self.assertEqual(result["download_report"]["sha256"],self.digest)
        self.assertEqual(self.repo.get(self.transfer["transfer_id"])["status"],
                         "completed")
        destination=self.root/"agent-game-data"/result["download_report"]["destination_ref"]
        self.assertTrue(destination.is_file())
        with destination.open("rb") as f:
            self.assertEqual(hashlib.file_digest(f,"sha256").hexdigest(),self.digest)
        self.assertNotEqual(result["agent_pid"],os.getpid())
        self.assertEqual(self.repo.get(self.transfer["transfer_id"])["transferred_bytes"],
                         self.source.stat().st_size)
        self.assertFalse(Path("/opt/dsm/runtime/hybrid-instance-storage").exists())
        if self.official:
            self.assertEqual(result["download_report"]["archive_type"],"zip")
            self.assertEqual(result["download_report"]["archive_entries"],2090)
        print("DSM1013_TWO_SYSTEMD_OFFICIAL_ZIP_PASS" if self.official
              else "DSM1013_TWO_SYSTEMD_SERVICES_PASS",json.dumps({
            "controller_unit":self.controller_unit,
            "agent_unit":self.agent_unit,
            "heartbeat":"real_dispatch_heartbeat",
            "agent_download":"real_artifact_transfer_client",
            "result":"durable_completed",
            "agent_credential":"authenticated",
            "disposable_synthetic_zip":not self.official,
            "official_serverpack_verified":self.official,
            "zip_bytes":self.source.stat().st_size,
            "localhost_only":True,"production_touched":False,
        },sort_keys=True),flush=True)

if __name__=="__main__":
    if len(sys.argv)==3 and sys.argv[1] in {"controller","agent"}:
        config=json.loads(Path(sys.argv[2]).read_text())
        if sys.argv[1]=="controller":_controller(config)
        else:_agent(config)
    else:
        unittest.main(verbosity=2)
