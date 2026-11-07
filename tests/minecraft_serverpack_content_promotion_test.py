from __future__ import annotations
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/"core",ROOT/"agents/common"):
    sys.path.insert(0,str(path))
from minecraft_serverpack_content_promotion import (
    promote_verified_sources,recover_source_promotion,ServerPackContentSyncError)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        r=Path(t.name);self.rec=r/"recovery";self.rec.mkdir()
        self.stage=r/"stage";(self.stage/"parent/mods").mkdir(parents=True)
        (self.stage/"children/child").mkdir(parents=True)
        self.parent=r/"live/pack";self.child=r/"live/mods"
        self.parent.mkdir(parents=True);self.child.mkdir(parents=True)
        (self.parent/"old.conf").write_text("keep")
        (self.child/"old").mkdir();(self.child/"old/old.jar").write_bytes(b"old")
        for p in (self.stage/"parent/mods/m.jar",self.stage/"children/child/m.jar"):
            p.write_bytes(b"new")
        self.sha="a"*64
        manifest={"kind":"VerifiedServerPackContentSources","instance_id":"inst",
                  "candidate_sha256":self.sha,
                  "files":[{"content_id":"child","filename":"m.jar",
                            "sha256":hashlib.sha256(b"new").hexdigest(),"size_bytes":3}]}
        (self.stage/"verified-source-manifest.json").write_text(json.dumps(manifest))
        self.db=(8,self.sha)

    def run_promotion(self,checkpoint=None):
        return promote_verified_sources(
            prepared=self.stage,parent_live=self.parent,children_live=self.child,
            recovery=self.rec,instance_id="inst",candidate_sha256=self.sha,
            revision=8,controller_state=lambda:self.db,checkpoint=checkpoint)

    def test_success_retains_rollback_sources(self):
        self.assertEqual(self.run_promotion()["status"],"committed")
        self.assertEqual((self.rec/"previous-parent/old.conf").read_text(),"keep")
        self.assertEqual((self.parent/"mods/m.jar").read_bytes(),b"new")
        self.assertEqual(recover_source_promotion(self.rec/"promotion.json"),"committed")

    def test_cas_mismatch_never_swaps(self):
        self.db=(7,self.sha)
        with self.assertRaisesRegex(ServerPackContentSyncError,"CAS mismatch"):
            self.run_promotion()
        self.assertEqual((self.parent/"old.conf").read_text(),"keep")
        self.assertFalse((self.rec/"promotion.json").exists())

    def test_tampered_stage_never_swaps(self):
        (self.stage/"children/child/m.jar").write_bytes(b"other")
        with self.assertRaisesRegex(ServerPackContentSyncError,"hash mismatch"):
            self.run_promotion()
        self.assertEqual((self.parent/"old.conf").read_text(),"keep")

    def test_reject_prepared_path_traversal(self):
        manifest=json.loads((self.stage/"verified-source-manifest.json").read_text())
        manifest["files"][0]["filename"]="../../outside.jar"
        (self.stage/"verified-source-manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ServerPackContentSyncError,"unsafe prepared JAR filename"):
            self.run_promotion()
        self.assertEqual((self.parent/"old.conf").read_text(),"keep")

    def test_reject_duplicate_prepared_children(self):
        manifest=json.loads((self.stage/"verified-source-manifest.json").read_text())
        manifest["files"].append(dict(manifest["files"][0]))
        (self.stage/"verified-source-manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ServerPackContentSyncError,"duplicate prepared child"):
            self.run_promotion()

    def test_change_in_controller_revision_after_swap_rolls_back(self):
        checks=[0]
        def state():
            checks[0]+=1
            return (8,self.sha) if checks[0]==1 else (9,self.sha)
        with self.assertRaisesRegex(ServerPackContentSyncError,"CAS changed"):
            promote_verified_sources(prepared=self.stage,parent_live=self.parent,
                children_live=self.child,recovery=self.rec,instance_id="inst",
                candidate_sha256=self.sha,revision=8,controller_state=state)
        self.assertEqual((self.parent/"old.conf").read_text(),"keep")
        self.assertEqual((self.child/"old/old.jar").read_bytes(),b"old")

    def test_exception_rolls_back_immediately(self):
        def fail(marker):
            if marker=="promoted_0":raise RuntimeError("inject")
        with self.assertRaisesRegex(RuntimeError,"inject"):
            self.run_promotion(fail)
        self.assertEqual((self.parent/"old.conf").read_text(),"keep")
        self.assertEqual((self.child/"old/old.jar").read_bytes(),b"old")
        self.assertEqual(recover_source_promotion(self.rec/"promotion.json"),"rolled_back")

    def test_process_death_after_backup_recovers(self):
        def crash(marker):
            if marker=="backup_0":raise SystemExit()
        with self.assertRaises(SystemExit):
            self.run_promotion(crash)
        self.assertFalse(self.parent.exists())
        self.assertEqual(recover_source_promotion(self.rec/"promotion.json"),"rolled_back")
        self.assertEqual((self.parent/"old.conf").read_text(),"keep")

    def test_process_death_after_both_swaps_recovers(self):
        def crash(marker):
            if marker=="promoted_1":raise SystemExit()
        with self.assertRaises(SystemExit):
            self.run_promotion(crash)
        self.assertEqual(recover_source_promotion(self.rec/"promotion.json"),"rolled_back")
        self.assertEqual((self.parent/"old.conf").read_text(),"keep")
        self.assertEqual((self.child/"old/old.jar").read_bytes(),b"old")
        self.assertEqual(recover_source_promotion(self.rec/"promotion.json"),"rolled_back")


if __name__=="__main__":unittest.main()
