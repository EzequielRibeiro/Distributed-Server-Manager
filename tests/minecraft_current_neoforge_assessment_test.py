import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"dashboard"))
from minecraft_current_neoforge_assessment import assess_current_neoforge as assess
F={"status":"failed","agent_id":"a","instance_id":"i","completed_at":"2026-10-23T20:00:00Z"}
E={"event_type":"MINECRAFT_NEOFORGE_CURRENT_VERIFIED","source":"controller.authenticated_agent_current_neoforge","agent_id":"a","instance_id":"i","occurred_at":"2026-10-24T09:00:00Z","data":{"proof_scope":"current_runtime_only","loader_version":"26.1.2.94"}}
H={"instance_id":"i","reported_at":"2026-10-24T10:00:00Z","observed_state":"running","reconcile_status":"healthy","health":"healthy"}
def run(f=F,e=E,h=H):return assess(agent_id="a",instance_id="i",failed_provision=f,attestation_events=[e],runtime_health=h)
class CurrentAssessmentTests(unittest.TestCase):
 def test_current_verified_not_historical_recovery(self):
  v=run();self.assertEqual(v["status"],"current_runtime_verified");self.assertFalse(v["allow_clear_previous_failure"]);self.assertFalse(v["historical_recovery_verified"])
 def test_wrong_agent_rejected(self):
  self.assertEqual(run(e={**E,"agent_id":"b"})["status"],"unverified")
 def test_old_proof_rejected(self):
  self.assertEqual(run(e={**E,"occurred_at":"2026-10-22T00:00:00Z"})["status"],"unverified")
 def test_health_before_proof_rejected(self):
  self.assertEqual(run(h={**H,"reported_at":"2026-10-24T08:00:00Z"})["status"],"awaiting_current_health")
 def test_unhealthy_rejected(self):
  self.assertEqual(run(h={**H,"reconcile_status":"degraded"})["status"],"current_runtime_unhealthy")
 def test_new_failure_rejected(self):
  self.assertEqual(run(f={**F,"completed_at":"2026-10-24T11:00:00Z"})["status"],"unverified")
if __name__=="__main__":unittest.main()
