from __future__ import annotations
import hashlib,json,pathlib,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/"database",ROOT/"core",ROOT/"tests"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from minecraft_serverpack_pending_publication_atomic_test import AtomicPendingPublicationTest
from core.minecraft_serverpack_pending_commit import build_pending_bundle_commit
from minecraft_serverpack_content_convergence import (
 verify_serverpack_content_convergence,ServerPackConvergenceError)


class ContentConvergenceTests(unittest.TestCase):
 def setUp(self):
  self.fixture=AtomicPendingPublicationTest(methodName="test_completed_agent_result_publishes_bundle_in_same_completion_transaction")
  self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=pathlib.Path(self.temp.name);self.iid="pr855-controller-atomic"
  self.agent="pr839-isolated-agent"
  self.content=b"j"*123
  self.digest=hashlib.sha256(self.content).hexdigest()
  original=self.fixture.pending()
  child=original["children"][0]
  child["artifact"]["filename"]="mod-a.jar"
  child["artifact"]["sha256"]=self.digest
  child["artifact"]["size_bytes"]=len(self.content)
  original["bundle"]["members"][0]["artifact"]=child["artifact"]
  self.pending=build_pending_bundle_commit(
   **{k:original[k] for k in ("instance_id","content_id","transfer_id",
       "migration_plan_sha256","expected_previous_revision","parent","bundle","children","requested_by")})
  self.repo,self.op=self.fixture.enqueue(self.pending)
  self.backend=self.fixture.backend
  self.runtime=self.root/"runtime"
  self.states=self.root/"managed"
  self.snapshot=self.root/"activation.json"
  self.kwargs={"backend":self.backend,"provisioning_id":self.op["provisioning_id"],
   "agent_id":self.agent,"instance_id":self.iid,
   "candidate_sha256":self.pending["candidate_sha256"],
   "managed_content_dir":self.states,"activation_snapshot_path":self.snapshot,
   "runtime_dir":self.runtime}

 def complete(self):
  self.repo.apply_result(self.agent,self.fixture.completed(self.op,self.pending))
  with self.backend.connect() as db:
   rows=db.execute("SELECT content_id,revision,checksum,version,desired_state,artifact_json FROM content_assignments WHERE instance_id=?",(self.iid,)).fetchall()
  self.states.mkdir()
  src=self.runtime/"content/modpacks/atm11/mods"
  child=self.runtime/"content/mods/mod-a"
  source=self.runtime/"mods"
  for path in (src,child,source):path.mkdir(parents=True)
  for path in (src/"mod-a.jar",child/"mod-a.jar",source/"mod-a.jar"):
   path.write_bytes(self.content)
  entries=[]
  for record in rows:
   cid=record["content_id"]
   location=self.runtime/"content/modpacks/atm11" if cid=="atm11" else child
   state={"instance_id":self.iid,"content_id":cid,"desired_state":"installed",
    "status":"applied","desired_revision":record["revision"],
    "applied_revision":record["revision"],"desired_checksum":record["checksum"],
    "applied_checksum":record["checksum"],"installed_version":record["version"],
    "security_state":"clean","applied_security_state":"clean",
    "attestation_candidate_sha256":self.pending["candidate_sha256"],
    "managed_path":str(location)}
   (self.states/(cid+".json")).write_text(json.dumps(state))
   entries.append({"content_id":cid,"managed_path":str(location)})
   with self.backend.transaction() as db:
    db.execute("""INSERT INTO agent_content_state
     (agent_id,instance_id,content_id,desired_revision,applied_revision,desired_checksum,applied_checksum,status,installed_version,last_error,reported_at,updated_at,security_state)
     VALUES (?,?,?,?,?,?,?,?,?,NULL,'now','now','clean')""",
     (self.agent,self.iid,cid,record["revision"],record["revision"],record["checksum"],record["checksum"],"applied",record["version"]))
  data={"kind":"CapivaraContentActivationSnapshot","instance_id":self.iid,
        "schema_version":1,"entries":entries}
  data["checksum"]=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
  self.snapshot.write_text(json.dumps(data))

 def verify(self):
  return verify_serverpack_content_convergence(**self.kwargs)

 def test_ready_after_authoritative_publication_and_all_sources(self):
  self.complete()
  receipt=self.verify()
  self.assertEqual(receipt["status"],"ready")
  self.assertEqual(receipt["mods_verified"],1)
  self.assertEqual(receipt["installed_content"],2)

 def test_missing_agent_reports_block(self):
  self.complete()
  with self.backend.transaction() as db:
   db.execute("DELETE FROM agent_content_state WHERE instance_id=? AND content_id=?",(self.iid,"mod-a"))
  with self.assertRaisesRegex(ServerPackConvergenceError,"incomplete"):
   self.verify()

 def test_corrupt_child_source_blocks(self):
  self.complete()
  (self.runtime/"content/mods/mod-a/mod-a.jar").write_bytes(b"tamper")
  with self.assertRaisesRegex(ServerPackConvergenceError,"mod content differs"):
   self.verify()

 def test_stale_local_state_blocks(self):
  self.complete()
  path=self.states/"mod-a.json";state=json.loads(path.read_text())
  state["applied_revision"]=0;path.write_text(json.dumps(state))
  with self.assertRaisesRegex(ServerPackConvergenceError,"local Agent state not converged"):
   self.verify()

 def test_snapshot_checksum_mismatch_blocks(self):
  self.complete()
  snap=json.loads(self.snapshot.read_text());snap["entries"]=[]
  self.snapshot.write_text(json.dumps(snap))
  with self.assertRaisesRegex(ServerPackConvergenceError,"snapshot checksum mismatch"):
   self.verify()

 def test_symlinked_mod_directory_is_rejected(self):
  self.complete()
  path=self.runtime/"content/mods/mod-a"
  relocated=self.root/"external-mod"
  path.rename(relocated)
  path.symlink_to(relocated,target_is_directory=True)
  with self.assertRaisesRegex(ServerPackConvergenceError,"unsafe managed mod directory"):
   self.verify()

 def test_unverified_security_blocks(self):
  self.complete()
  with self.backend.transaction() as db:
   db.execute("UPDATE agent_content_state SET security_state='unscanned' WHERE instance_id=? AND content_id=?",(self.iid,"mod-a"))
  with self.assertRaisesRegex(ServerPackConvergenceError,"unverified security"):
   self.verify()

 def test_controller_not_completed_blocks(self):
  with self.assertRaisesRegex(Exception,"not completed"):
   self.verify()


if __name__=="__main__":unittest.main()
