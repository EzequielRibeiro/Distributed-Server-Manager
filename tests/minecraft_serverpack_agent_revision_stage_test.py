import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for x in (ROOT,ROOT/"agents/common",ROOT/"agents/linux/runtime"):sys.path.insert(0,str(x))
from minecraft_serverpack_agent_revision_stage import stage_serverpack_agent_revision,ServerPackRevisionStageError


class RevisionStagingTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
  root=Path(t.name)
  self.runtime=root/"runtime"
  for path in (self.runtime/"content/modpacks",self.runtime/"content/mods"):path.mkdir(parents=True)
  self.dest=root/"new-revision"
  self.receipt={"kind":"VerifiedServerPackControllerReceipt","status":"verified",
   "instance_id":"mc005","agent_id":"agent","candidate_sha256":"a"*64,
   "bundle_revision":8,"content_id":"pack","child_count":1}
  def item(cid,desired="installed"):
   return {"instance_id":"mc005","content_id":cid,"content_type":"modpack" if cid=="pack" else "mod",
    "desired_state":desired,"revision":8,"checksum":"sha-"+cid,"version":"v14",
    "provider":"local","game_id":"minecraft","activation_state":"enabled",
    "artifact":{"filename":cid+".jar"},"metadata":{}}
  self.assignments=[item("pack"),item("mod-1"),item("old","absent")]
  self.scans=dict(parent="clean",children="clean",running="clean")
 def prepare(self):
  return stage_serverpack_agent_revision(assignments=self.assignments,
    receipt=self.receipt,parent_content_id="pack",child_content_ids={"mod-1"},
    live_runtime=self.runtime,staging_dir=self.dest,scan_evidence=self.scans)
 def test_prepared_and_replay(self):
  first=self.prepare();second=self.prepare()
  self.assertEqual(first["status"],"prepared")
  self.assertEqual(second["status"],"already_prepared")
  self.assertEqual(first["total"],3)
  self.assertEqual(len(json.loads((self.dest/"activation.json").read_text())["entries"]),2)
 def test_invalid_security_fails_without_stage(self):
  self.scans["parent"]="unscanned"
  with self.assertRaisesRegex(ServerPackRevisionStageError,"YARA-X"):
   self.prepare()
  self.assertFalse(self.dest.exists())
 def test_duplicate_assignment_fails(self):
  self.assignments.append(dict(self.assignments[1]))
  with self.assertRaisesRegex(ServerPackRevisionStageError,"duplicate"):
   self.prepare()
 def test_wrong_desired_state_fails(self):
  self.assignments[1]["desired_state"]="absent"
  with self.assertRaisesRegex(ServerPackRevisionStageError,"desired content"):
   self.prepare()
 def test_wrong_instance_fails(self):
  self.assignments[1]["instance_id"]="other"
  with self.assertRaisesRegex(ServerPackRevisionStageError,"another instance"):
   self.prepare()
 def test_stale_replay_fails(self):
  self.prepare();self.assignments[1]["checksum"]="new-sha"
  with self.assertRaisesRegex(ServerPackRevisionStageError,"differ"):
   self.prepare()
 def test_corrupt_snapshot_blocks_replay(self):
  self.prepare()
  (self.dest/"activation.json").write_text('{"checksum":"tampered"}')
  with self.assertRaisesRegex(ServerPackRevisionStageError,"snapshot changed"):
   self.prepare()
if __name__=="__main__":unittest.main()
