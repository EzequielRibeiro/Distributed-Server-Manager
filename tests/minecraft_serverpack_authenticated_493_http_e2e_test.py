"""Isolated 493-assignment Server Pack HTTP Agent->Controller report scale rehearsal.

Uses real credential authentication and HTTP handler, SQLite only, durable Agent outbox.
Production databases/services and customer files are never opened.
"""
from __future__ import annotations
from contextlib import ExitStack
import hashlib, json, os, sys, tempfile, threading, unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT,ROOT/"database",ROOT/"dashboard",ROOT/"core",ROOT/"agents/common",ROOT/"agents/linux/runtime",ROOT/"tests"):
    if str(folder) not in sys.path: sys.path.insert(0,str(folder))
from minecraft_serverpack_pending_publication_atomic_test import (
    bundle, parent, child, local_artifact)
import minecraft_serverpack_pending_publication_atomic_test as atomic_fixture
from core.minecraft_serverpack_pending_commit import build_pending_bundle_commit
from core.agent_identity import secret_digest
from minecraft_serverpack_report_outbox import (
    queue_serverpack_report_delivery, read_serverpack_report_delivery,
    acknowledge_serverpack_report_delivery)

class LargeRealCredentialHTTP(unittest.TestCase):
    def setUp(self):
        self.fixture=atomic_fixture.AtomicPendingPublicationTest(
            methodName="test_completed_agent_result_publishes_bundle_in_same_completion_transaction")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f=self.fixture
        # Actual ATM11 scale: 282 old -> 291 new (81 shared), 201 absent, one parent.
        shared=["mod-a"]+[f"common-{i:03d}" for i in range(80)]
        oldids=shared+[f"legacy-{i:03d}" for i in range(201)]
        oldpack=bundle("0.13","26.1.2.94","a")
        oldchildren=[]
        oldpack["members"]=[]
        for cid in oldids:
            artifact=local_artifact(cid,"26.1.2.94","a")
            oldpack["members"].append({"content_id":cid,"path":f"mods/{cid}.jar",
                 "required":True,"artifact":artifact})
            c=child("0.13","26.1.2.94","a")
            c.update(content_id=cid,target=f"mods/{cid}",artifact=artifact)
            oldchildren.append(c)
        self.assertEqual(len(oldids),282)
        b=f.content.put_bundle(parent("0.13"),oldpack,oldchildren,requested_by="customer")
        self.assertEqual(b["bundle_revision"],2)
        newids=shared+[f"new-mod-{i:03d}" for i in range(210)]
        self.assertEqual(len(newids),291)
        newpack=bundle("0.14","26.1.2.109","b")
        newpack["members"]=[]
        newchildren=[]
        for cid in newids:
            artifact=local_artifact(cid,"26.1.2.109","b")
            newpack["members"].append({"content_id":cid,"path":f"mods/{cid}.jar",
                 "required":True,"artifact":artifact})
            c=child("0.14","26.1.2.109","b")
            c.update(content_id=cid,target=f"mods/{cid}",artifact=artifact)
            newchildren.append(c)
        self.pending=build_pending_bundle_commit(
            instance_id=f.iid if hasattr(f,"iid") else "pr855-controller-atomic",
            content_id="atm11",transfer_id="transfer-atomic",
            migration_plan_sha256="c"*64,expected_previous_revision=2,
            parent=parent("0.14"),bundle=newpack,children=newchildren,
            requested_by="customer")
        self.repo,self.op=f.enqueue(self.pending)
        completed=f.completed(self.op,self.pending)
        self.assertEqual(self.repo.apply_result("pr839-isolated-agent",completed)["status"],"completed")
        self.iid="pr855-controller-atomic"
        self.agent="pr839-isolated-agent"
        self.backend=f.backend
        with self.backend.connect() as con:
            rows=con.execute("SELECT content_id,revision,checksum,version,desired_state "
               "FROM content_assignments WHERE instance_id=?",(self.iid,)).fetchall()
        self.assertEqual(len(rows),493)
        self.assertEqual(sum(x["desired_state"]=="installed" for x in rows),292)
        self.assertEqual(sum(x["desired_state"]=="absent" for x in rows),201)
        candidate=self.pending["candidate_sha256"]
        reports=[]
        for row in rows:
            active=row["desired_state"]=="installed"
            reports.append({
                "agent_id":self.agent,"instance_id":self.iid,
                "content_id":row["content_id"],"status":"applied",
                "desired_state":row["desired_state"],"desired_revision":row["revision"],
                "applied_revision":row["revision"],"desired_checksum":row["checksum"],
                "applied_checksum":row["checksum"],
                "installed_version":row["version"] if active else None,
                "security_state":"clean" if active else "unscanned",
                "attestation_candidate_sha256":candidate,"last_error":None,
            })
        self.reports=reports
        self.temp=tempfile.TemporaryDirectory(prefix="dsm-1013-493-auth-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        states=self.root/"states";states.mkdir()
        snap=self.root/"snapshot.json"
        self.paths={
            "source_promotion_journal":self.root/"source.json",
            "state_promotion_journal":self.root/"local.json",
            "staged_manifest":self.root/"manifest.json",
            "prepared_reports":self.root/"prepared.json",
            "active_states":states,
            "active_snapshot":snap,
        }
        def write(path,data):path.write_text(json.dumps(data,sort_keys=True))
        write(self.paths["source_promotion_journal"],{
            "kind":"VerifiedSourcePromotion","phase":"committed",
            "instance_id":self.iid,"candidate_sha256":candidate,"revision":3})
        write(self.paths["state_promotion_journal"],{
            "kind":"ServerPackLocalStatePromotion","phase":"committed",
            "instance_id":self.iid,"candidate_sha256":candidate,"bundle_revision":3,
            "entries":[{"active":str(states)},{"active":str(snap)}]})
        active_ids=[]
        for report in reports:
            state={k:v for k,v in report.items() if k!="agent_id"}
            active=report["desired_state"]=="installed"
            state["applied_security_state"]="clean" if active else "unscanned"
            if active:
                state["managed_path"]=f"/isolated/{report['content_id']}"
                active_ids.append(report["content_id"])
            write(states/(report["content_id"]+".json"),state)
        snapshot={"kind":"CapivaraContentActivationSnapshot","instance_id":self.iid,
          "schema_version":1,"entries":[{"content_id":cid} for cid in sorted(active_ids)]}
        snapshot["checksum"]=hashlib.sha256(json.dumps(snapshot,sort_keys=True,
           separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        write(snap,snapshot)
        write(self.paths["staged_manifest"],{
            "kind":"ServerPackPreparedAgentRevision","instance_id":self.iid,
            "candidate_sha256":candidate,"bundle_revision":3,
            "total":493,"installed":292,
            "activation_checksum":snapshot["checksum"]})
        write(self.paths["prepared_reports"],reports)
        self.offer={"kind":"VerifiedServerPackRecoveryOffer","status":"verified",
                    "provisioning_id":self.op["provisioning_id"],"instance_id":self.iid,
                    "candidate_sha256":candidate,"bundle_revision":3}
        self.assertEqual(queue_serverpack_report_delivery(
            state_dir=self.root,offer=self.offer,agent_id=self.agent,**self.paths),"queued")
        self.assertEqual(queue_serverpack_report_delivery(
            state_dir=self.root,offer=self.offer,agent_id=self.agent,**self.paths),"already_queued")
        self.queued=read_serverpack_report_delivery(self.root)
        self.assertIsNotNone(self.queued)
        self.assertEqual(len(self.queued[0]["reports"]),493)
        self.secret="test-only-dsm-scale493-credential"
        self.credential_id="cred-dsm-1013-scale493"
        self.fingerprint="test-scale493-fingerprint"
        with self.backend.transaction() as con:
            con.execute("INSERT INTO agent_credentials "
                "(id,agent_id,controller_id,credential_type,secret_hash,fingerprint,status) "
                "VALUES (?,?,?,?,?,?,?)",
                (self.credential_id,self.agent,"ctrl","opaque-v1",
                 secret_digest(self.secret),self.fingerprint,"active"))
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name in ("_attach_uninstall_state","_attach_update_state","_attach_provisioning_state",
                     "_attach_game_data_state","_attach_instance_state","_attach_doctor_state",
                     "_reconcile_link_incident","_attach_backup_clone_state"):
            self.stack.enter_context(patch("agent_remote_http."+name))
        self.stack.enter_context(patch("agent_remote_http.record_agent_heartbeat",
            return_value={"agent_id":self.agent,"health_status":"online"}))
        self.stack.enter_context(patch("agent_remote_http.validated_heartbeat_recovery_claims",
            return_value=[]))
        self.stack.enter_context(patch("minecraft_recovery_heartbeat_claims.owned_instance_ids_for_agent",
            return_value=set()))
        self.stack.enter_context(patch.dict(os.environ,
            {"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"1"}))
        backend=self.backend
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path!="/api/agent/heartbeat":
                    self.send_error(404);return
                size=int(self.headers.get("Content-Length","0"))
                if size<=0 or size>12*1024*1024:
                    self.send_error(413);return
                body=json.loads(self.rfile.read(size))
                from agent_remote_http import dispatch_heartbeat
                status,response=dispatch_heartbeat(body,headers=self.headers,backend=backend)
                data=json.dumps(response).encode()
                self.send_response(status)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self,*_args):pass
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join,2)
        self.addCleanup(self.server.shutdown)

    def count(self):
        with self.backend.connect() as con:
            return con.execute("SELECT COUNT(*) AS n FROM agent_content_state WHERE instance_id=?",
              (self.iid,)).fetchone()["n"]
    def send(self,payload,secret=None):
        data=json.dumps({"serverpack_report_delivery":payload},
             separators=(",",":")).encode()
        self.assertLess(len(data),12*1024*1024)
        url=f"http://127.0.0.1:{self.server.server_port}/api/agent/heartbeat"
        request=Request(url,method="POST",data=data,headers={
            "X-Capivara-Agent-Credential":self.credential_id,
            "X-Capivara-Agent-Secret":secret or self.secret,
            "X-Capivara-Agent-Fingerprint":self.fingerprint,
            "Content-Type":"application/json"})
        with urlopen(request,timeout=60) as response:
            return response.status,json.loads(response.read()),len(data)

    def test_authentic_credentials_493_atomic_and_ack_lost_response_replay(self):
        payload,filename=self.queued
        with self.assertRaises(HTTPError) as invalid:
            self.send(payload,secret="invalid-credential")
        self.assertEqual(invalid.exception.code,401)
        self.assertEqual(self.count(),0)
        corrupted=dict(payload)
        corrupted["reports"]=payload["reports"][:-1]
        status,bad,_=self.send(corrupted)
        self.assertEqual(status,200)
        self.assertEqual(bad["serverpack_report_delivery"]["status"],"rejected")
        self.assertEqual(self.count(),0)
        status,disabled,_=None,None,0
        with patch.dict(os.environ,{"DSM_SERVERPACK_REPORT_DELIVERY_ENABLED":"0"}):
            status,disabled,_=self.send(payload)
        self.assertEqual(disabled["serverpack_report_delivery"]["status"],"disabled")
        self.assertEqual(self.count(),0)
        status,good,size=self.send(payload)
        self.assertEqual(status,200)
        self.assertEqual(good["serverpack_report_delivery"]["status"],"published")
        self.assertEqual(good["serverpack_report_delivery"]["reports"],493)
        self.assertEqual(self.count(),493)
        # Controller wrote all 493, but Agent loses the HTTP response and keeps its outbox.
        self.assertIsNotNone(read_serverpack_report_delivery(self.root))
        status,repeat,_=self.send(payload)
        self.assertEqual(repeat["serverpack_report_delivery"]["status"],"published")
        self.assertEqual(self.count(),493)
        self.assertTrue(acknowledge_serverpack_report_delivery(
            self.root,filename,payload,repeat["serverpack_report_delivery"]))
        self.assertIsNone(read_serverpack_report_delivery(self.root))
        print("AUTHENTIC_493_HTTP_PASS",json.dumps({
            "reports":493,"installed":292,"absent":201,
            "request_bytes":size,"real_credential_verified":True,
            "http_bad_credential":401,"truncated_batch_rejected":True,
            "disabled_no_writes":True,"atomic_publication":True,
            "lost_response_replay":True,"outbox_removed_only_after_ack":True,
            "db_kind":"disposable SQLite","host":"127.0.0.1:ephemeral",
            "production_untouched":True,
        },sort_keys=True),flush=True)

if __name__=="__main__":
    unittest.main(defaultTest="LargeRealCredentialHTTP", verbosity=2)
