from __future__ import annotations
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"agents/common"):sys.path.insert(0,str(p))
from minecraft_serverpack_report_delivery_payload import (
 build_committed_serverpack_report_delivery,ServerPackReportDeliveryError)


class ReportPayloadTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
  r=Path(temp.name)
  self.state=r/"states";self.state.mkdir()
  self.snapshot=r/"active.json"
  self.src=r/"source-journal.json";self.local=r/"local-journal.json"
  self.manifest=r/"manifest.json";self.reports=r/"reports.json"
  self.sha="f"*64
  self.offer=dict(kind="VerifiedServerPackRecoveryOffer",status="verified",
   provisioning_id="instance-provision-test",instance_id="mc005",
   candidate_sha256=self.sha,bundle_revision=8)
  self.write(self.src,dict(kind="VerifiedSourcePromotion",phase="committed",
   instance_id="mc005",candidate_sha256=self.sha,revision=8))
  self.write(self.local,dict(kind="ServerPackLocalStatePromotion",phase="committed",
   instance_id="mc005",candidate_sha256=self.sha,bundle_revision=8,
   entries=[{"active":str(self.state)},{"active":str(self.snapshot)}]))
  self.item={"agent_id":"agent","instance_id":"mc005","content_id":"mod-1",
   "status":"applied","desired_state":"installed","desired_revision":8,
   "applied_revision":8,"desired_checksum":"abc","applied_checksum":"abc",
   "installed_version":"0.14","security_state":"clean",
   "attestation_candidate_sha256":self.sha,"last_error":None}
  self.state_item={k:v for k,v in self.item.items() if k!="agent_id"}
  self.state_item.update(applied_security_state="clean",managed_path="/content/mod-1")
  self.write(self.state/"mod-1.json",self.state_item)
  identity=dict(kind="CapivaraContentActivationSnapshot",instance_id="mc005",
   schema_version=1,entries=[{"content_id":"mod-1"}])
  identity["checksum"]=hashlib.sha256(json.dumps(identity,sort_keys=True,
   separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
  self.write(self.snapshot,identity)
  self.write(self.manifest,dict(kind="ServerPackPreparedAgentRevision",
   instance_id="mc005",candidate_sha256=self.sha,bundle_revision=8,
   total=1,installed=1,activation_checksum=identity["checksum"]))
  self.write(self.reports,[self.item])
 def write(self,path,obj):path.write_text(json.dumps(obj))
 def payload(self):
  return build_committed_serverpack_report_delivery(
    offer=self.offer,agent_id="agent",source_promotion_journal=self.src,
    state_promotion_journal=self.local,staged_manifest=self.manifest,
    prepared_reports=self.reports,active_states=self.state,active_snapshot=self.snapshot)
 def test_complete_and_replay(self):
  self.assertEqual(self.payload()["reports"],[self.item])
  self.assertEqual(self.payload(),self.payload())
 def test_source_not_committed(self):
  d=json.loads(self.src.read_text());d["phase"]="promoting";self.write(self.src,d)
  with self.assertRaisesRegex(ServerPackReportDeliveryError,"sources not committed"):self.payload()
 def test_local_not_committed(self):
  d=json.loads(self.local.read_text());d["phase"]="rolled_back";self.write(self.local,d)
  with self.assertRaisesRegex(ServerPackReportDeliveryError,"states not committed"):self.payload()
 def test_foreign_state_path(self):
  d=json.loads(self.local.read_text());d["entries"][0]["active"]="/tmp/unrelated"
  self.write(self.local,d)
  with self.assertRaisesRegex(ServerPackReportDeliveryError,"points elsewhere"):self.payload()
 def test_tampered_active_snapshot(self):
  d=json.loads(self.snapshot.read_text());d["entries"]=[]
  self.write(self.snapshot,d)
  with self.assertRaisesRegex(ServerPackReportDeliveryError,"invalid activation checksum"):self.payload()
 def test_report_revision_mismatch(self):
  d=json.loads(self.reports.read_text());d[0]["applied_revision"]=7
  self.write(self.reports,d)
  with self.assertRaisesRegex(ServerPackReportDeliveryError,"report differs"):self.payload()
 def test_report_candidate_mismatch(self):
  d=json.loads(self.reports.read_text());d[0]["attestation_candidate_sha256"]="0"*64
  self.write(self.reports,d)
  with self.assertRaisesRegex(ServerPackReportDeliveryError,"report differs"):self.payload()
 def test_symlink_in_state_inventory_rejected(self):
  (self.state/"link.json").symlink_to(self.state/"mod-1.json")
  with self.assertRaisesRegex(ServerPackReportDeliveryError,"extra or unsafe"):self.payload()
 def test_foreign_agent_rejected(self):
  with self.assertRaisesRegex(ServerPackReportDeliveryError,"identity or commit"):build_committed_serverpack_report_delivery(
    offer=self.offer,agent_id="other",source_promotion_journal=self.src,
    state_promotion_journal=self.local,staged_manifest=self.manifest,
    prepared_reports=self.reports,active_states=self.state,active_snapshot=self.snapshot)
 def test_missing_controller_offer(self):
  self.offer["status"]="pending"
  with self.assertRaisesRegex(ServerPackReportDeliveryError,"not verified"):self.payload()


if __name__=="__main__":unittest.main()
