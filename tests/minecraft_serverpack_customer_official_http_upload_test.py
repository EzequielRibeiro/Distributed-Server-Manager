"""Disposable real HTTP customer POST/PUT -> authenticated Agent download -> ACK -> preview.

The official 0.14 ZIP is streamed; no production services, worlds or databases.
CurseForge metadata stays a controlled fixture, not a live API lookup.
"""
from __future__ import annotations
import hashlib, http.client, importlib, json, os, sys, threading, unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
for folder in (ROOT,ROOT/"tests",ROOT/"dashboard",ROOT/"database",ROOT/"core",
               ROOT/"agents/linux/runtime",ROOT/"agents/common"):
    if str(folder) not in sys.path:sys.path.insert(0,str(folder))
from minecraft_serverpack_customer_official_preview_session_test import (
    CustomerOfficialPreviewSessionE2E,IID,AGENT,NAME,SHA_014)
from artifact_transfer_repository import ArtifactTransferRepository
from artifact_transfer_http import install_artifact_transfer_http
from core.agent_identity import secret_digest

class OfficialCustomerRealPutAgentAckE2E(CustomerOfficialPreviewSessionE2E):
    test_customer_cookie_real_014_zip_preview_revalidate_and_deny_unsafe=None

    def setUp(self):
        if (os.environ.get("DSM_1013_OFFICIAL_REAL_UPLOAD")!="1"
                or os.environ.get("GITHUB_ACTIONS")!="true"
                or os.environ.get("RUNNER_ENVIRONMENT")!="github-hosted"):
            self.skipTest("official upload runs only in disposable GitHub-hosted CI")
        super().setUp()
        scratch=Path(self.fixture.temp.name)
        controller=scratch/"controller-files"
        controller.mkdir()
        self.game_data=scratch/"agent-game-data"
        self.game_data.mkdir()
        self.transfers=ArtifactTransferRepository(self.backend,controller)
        self.service.transfers=self.transfers
        self.cred_id="isolated-dsm1013-credential"
        self.cred_secret="isolated-dsm1013-test-only"
        self.fingerprint="isolated-dsm1013-fingerprint"
        with self.backend.transaction() as db:
            db.execute("INSERT INTO agent_credentials "
                "(id,agent_id,controller_id,credential_type,secret_hash,fingerprint,status)"
                " VALUES (?,?,?,?,?,?,?)",
                (self.cred_id,AGENT,"ctrl","opaque-v1",
                 secret_digest(self.cred_secret),self.fingerprint,"active"))
        backend=self.backend
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send_json(self,status,body):
                data=json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def unauthorized(self):self.send_json(401,{"error":"unauthorized"})
            def do_GET(self):self.send_json(404,{"error":"not_found"})
            def do_POST(self):self.send_json(404,{"error":"not_found"})
        legacy=SimpleNamespace(DashboardHandler=Handler,DSM_ROOT=controller,
             DATABASE_FILE="unused",dashboard_repository=lambda _p:SimpleNamespace(backend=backend))
        install_artifact_transfer_http(legacy,lambda _h:None)
        self.agent_http=ThreadingHTTPServer(("127.0.0.1",0),legacy.DashboardHandler)
        self.agent_thread=threading.Thread(target=self.agent_http.serve_forever,daemon=True)
        self.agent_thread.start()
        self.addCleanup(self._stop_agent)
        self.agent_env=patch.dict(os.environ,{
            "CAPIVARA_AGENT_STATE_DIR":str(scratch/"agent-state"),
            "CAPIVARA_GAME_DATA_ROOT":str(self.game_data),
            "CAPIVARA_AGENT_GAME_DATA_ROOT":str(self.game_data)})
        self.agent_env.start()
        self.addCleanup(self.agent_env.stop)
        import content_upload_quarantine as quarantine
        import artifact_transfer_client as client
        self.quarantine=importlib.reload(quarantine)
        self.client=importlib.reload(client)

    def _stop_agent(self):
        self.agent_http.shutdown()
        self.agent_http.server_close()
        self.agent_thread.join(timeout=5)

    def _put_real_zip(self,transfer_id):
        c=http.client.HTTPConnection("127.0.0.1",self.http.server_port,timeout=240)
        try:
            c.putrequest("PUT","/api/customer/instance/workspace/content/upload?transfer_id="+transfer_id)
            for k,v in {
                "X-Capivara-Auth-Area":"customer",
                "Cookie":"capivara_customer_session="+self.customer_token,
                "Content-Length":str(self.zip.stat().st_size),
                "Content-Type":"application/octet-stream",
            }.items():c.putheader(k,v)
            c.endheaders()
            with self.zip.open("rb") as f:
                for chunk in iter(lambda:f.read(1024*1024),b""):c.send(chunk)
            response=c.getresponse()
            return response.status,json.loads(response.read())
        finally:c.close()

    def test_customer_upload_agent_real_get_ack_and_official_preview(self):
        endpoint="/api/customer/instance/workspace/content/upload"
        self.assertEqual(self.call(endpoint,{"instance_id":IID,"filename":NAME})[0],401)
        status,created=self.call(endpoint,{"instance_id":IID,"filename":NAME},
                                 token=self.customer_token)
        self.assertEqual(status,201,created)
        transfer_id=created["transfer"]["transfer_id"]
        self.assertEqual(created["transfer"]["status"],"staging")
        status,staged=self._put_real_zip(transfer_id)
        self.assertEqual(status,201,staged)
        self.assertEqual(staged["transfer"]["status"],"queued")
        self.assertEqual(staged["transfer"]["sha256"],SHA_014)
        self.assertEqual(staged["transfer"]["size_bytes"],self.zip.stat().st_size)
        status,queued=self.call(endpoint+"/status?transfer_id="+transfer_id,
                                token=self.customer_token)
        self.assertEqual((status,queued["transfer"]["status"]),(200,"queued"))
        cmd=self.transfers.command_for_agent(AGENT)
        self.assertEqual(cmd["transfer_id"],transfer_id)
        self.assertEqual(cmd["purpose"],"content_upload")
        with self.assertRaises(HTTPError) as denied:
            urlopen("http://127.0.0.1:"+str(self.agent_http.server_port)+
                "/api/agent/artifacts/download?transfer_id="+transfer_id,timeout=5)
        self.assertEqual(denied.exception.code,401)
        config={"controller_url":"http://127.0.0.1:"+str(self.agent_http.server_port),
                "credential_id":self.cred_id,"credential_secret":self.cred_secret,
                "fingerprint":self.fingerprint}
        result=self.client.handle_command(config,cmd)
        self.assertEqual(result["status"],"completed",result)
        self.assertEqual(result["archive_type"],"zip")
        self.assertGreater(result["archive_entries"],291)
        self.assertEqual(result["sha256"],SHA_014)
        self.assertEqual(result["transferred_bytes"],self.zip.stat().st_size)
        destination=self.game_data/result["destination_ref"]
        self.assertEqual(destination,
            self.quarantine.quarantine_destination(IID,transfer_id,NAME))
        with destination.open("rb") as f:
            self.assertEqual(hashlib.file_digest(f,"sha256").hexdigest(),SHA_014)
        receipt=self.transfers.apply_agent_result(AGENT,result)
        self.assertEqual(receipt["status"],"completed")
        status,completed=self.call(endpoint+"/status?transfer_id="+transfer_id,
                                  token=self.customer_token)
        self.assertEqual((status,completed["transfer"]["status"]),(200,"completed"))
        preview_request={"instance_id":IID,"transfer_id":transfer_id,
            "content_id":"atm11","content_type":"modpack",
            "metadata":{"display_name":"All the Mods 11","serverpack":{
                "format":"official-serverpack-v1",
                "curseforge_project_id":"1148445",
                "curseforge_file_id":"9426897",
                "loader_version":"26.1.2.126"}}}
        status,preview=self.call(endpoint+"/preview",preview_request,
                                 token=self.customer_token)
        self.assertEqual(status,200,preview)
        data=preview["serverpack"]
        self.assertEqual(data["archive_sha256"],SHA_014)
        self.assertEqual(data["mod_count"],291)
        plan=data["update_plan"]
        self.assertEqual(plan["operation"],"staged_loader_migration_preview")
        self.assertEqual(plan["from_loader_version"],"26.1.2.124")
        self.assertEqual(plan["target_loader_version"],"26.1.2.126")
        self.assertFalse(plan["install_allowed"])
        status,attested=self.call(endpoint+"/migration/revalidate",
            {**preview_request,"migration_plan_sha256":plan["migration_plan_sha256"]},
            token=self.customer_token)
        self.assertEqual(status,200,attested)
        self.assertTrue(attested["migration"]["valid"])
        self.assertFalse(attested["migration"]["install_allowed"])
        self.assertEqual(self.fixture.content.bundle_history(IID,"atm11")[0]["revision"],2)
        self.assertEqual(self.client.handle_command(config,cmd),result)
        print("DSM1013_OFFICIAL_HTTP_UPLOAD_AGENT_ACK_PASS",json.dumps({
            "bytes":self.zip.stat().st_size,"sha256":SHA_014,
            "customer_create":201,"customer_put":201,
            "agent_get":"real_authenticated_http",
            "agent_quarantine_archive_entries":result["archive_entries"],
            "agent_ack":"real_sqlite","agent_result_idempotent":True,
            "preview":"real_zip_after_agent_ack","mods":291,
            "revision_unchanged":2,"provider_metadata":"controlled_fixture",
            "production_touched":False,"browser_tested":False,
            "systemd_agent_tested":False},sort_keys=True),flush=True)

if __name__=="__main__":
    unittest.main(verbosity=2)
