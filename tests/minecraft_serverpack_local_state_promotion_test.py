from __future__ import annotations
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"agents/common"):sys.path.insert(0,str(p))
from minecraft_serverpack_local_state_promotion import promote_local_state_snapshot,recover_local_state_promotion
from minecraft_serverpack_content_sync import ServerPackContentSyncError


class LocalStatePromotionTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
  r=Path(temp.name);self.root=r
  self.staged=r/"new-states";self.staged.mkdir()
  self.active=r/"states";self.active.mkdir()
  (self.active/"old.json").write_text('{"old":true}')
  self.new_snapshot=r/"new-snapshot.json";self.active_snapshot=r/"snapshot.json"
  self.active_snapshot.write_text('{"old":true}')
  self.recovery=r/"recovery";self.recovery.mkdir()
  self.sha="a"*64
  self.ids={"pack","child","old"};self.active_ids={"pack","child"}
  for cid in self.ids:
   installed=cid in self.active_ids
   state={"instance_id":"mc005","content_id":cid,"status":"applied",
    "desired_state":"installed" if installed else "absent",
    "security_state":"clean" if installed else "unscanned",
    "applied_security_state":"clean" if installed else "unscanned",
    "attestation_candidate_sha256":self.sha if installed else None,
    "installed_version":"v14" if installed else None,
    "managed_path":"/new/mods/"+cid if installed else None}
   (self.staged/(cid+".json")).write_text(json.dumps(state))
  snap={"kind":"CapivaraContentActivationSnapshot",
   "instance_id":"mc005","entries":[{"content_id":"pack"},{"content_id":"child"}]}
  snap["checksum"]=hashlib.sha256(json.dumps(snap,sort_keys=True,
    separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
  self.new_snapshot.write_text(json.dumps(snap))
  self.receipt=lambda:dict(kind="VerifiedServerPackControllerReceipt",status="verified",
    instance_id="mc005",candidate_sha256=self.sha,bundle_revision=8)
 def promote(self,checkpoint=None):
  return promote_local_state_snapshot(staged_states=self.staged,
   staged_snapshot=self.new_snapshot,active_states=self.active,
   active_snapshot=self.active_snapshot,recovery_dir=self.recovery,
   instance_id="mc005",candidate_sha256=self.sha,revision=8,
   expected_content_ids=self.ids,expected_active_ids=self.active_ids,
   controller_receipt=self.receipt,checkpoint=checkpoint)
 def test_promote_and_keep_previous_state(self):
  self.assertEqual(self.promote()["status"],"committed")
  self.assertEqual(len(list(self.active.glob("*.json"))),3)
  self.assertEqual(json.loads((self.recovery/"previous-states/old.json").read_text()),{"old":True})
  self.assertEqual(json.loads((self.recovery/"previous-snapshot.json").read_text()),{"old":True})
  self.assertEqual(recover_local_state_promotion(self.recovery/"local-state-promotion.json"),"committed")
 def test_missing_staged_child_blocks(self):
  (self.staged/"child.json").unlink()
  with self.assertRaisesRegex(ServerPackContentSyncError,"inventory"):
   self.promote()
  self.assertFalse((self.recovery/"local-state-promotion.json").exists())
 def test_missing_scan_blocks(self):
  path=self.staged/"child.json";d=json.loads(path.read_text());d["security_state"]="unscanned";path.write_text(json.dumps(d))
  with self.assertRaisesRegex(ServerPackContentSyncError,"unverified"):
   self.promote()
 def test_tampered_snapshot_checksum_blocks(self):
  snap=json.loads(self.new_snapshot.read_text());snap["entries"]=[]
  self.new_snapshot.write_text(json.dumps(snap))
  with self.assertRaisesRegex(ServerPackContentSyncError,"checksum mismatch"):
   self.promote()

 def test_bad_controller_blocks(self):
  self.receipt=lambda:{"status":"pending"}
  with self.assertRaisesRegex(ServerPackContentSyncError,"Controller did not"):
   self.promote()
 def test_crash_after_state_swap_recovers(self):
  def crash(phase):
   if phase=="promoted_0":raise SystemExit()
  with self.assertRaises(SystemExit):self.promote(crash)
  self.assertEqual(recover_local_state_promotion(self.recovery/"local-state-promotion.json"),"rolled_back")
  self.assertTrue((self.active/"old.json").exists())
  self.assertEqual(json.loads(self.active_snapshot.read_text()),{"old":True})
  self.assertEqual(len(list(self.staged.glob("*.json"))),3)
 def test_crash_after_both_swaps_recovers(self):
  def crash(phase):
   if phase=="promoted_1":raise SystemExit()
  with self.assertRaises(SystemExit):self.promote(crash)
  self.assertEqual(recover_local_state_promotion(self.recovery/"local-state-promotion.json"),"rolled_back")
  self.assertTrue((self.active/"old.json").exists())
  self.assertEqual(json.loads(self.active_snapshot.read_text()),{"old":True})
 def test_normal_exception_recovers(self):
  def fail(phase):
   if phase=="backup_1":raise RuntimeError("disk error")
  with self.assertRaisesRegex(RuntimeError,"disk error"):self.promote(fail)
  self.assertTrue((self.active/"old.json").exists())


if __name__=="__main__":unittest.main()
