import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard/workers'))
from dayz_timeout_evidence_gate import decide_timeout_evidence as decide

class TimeoutEvidenceGateTest(unittest.TestCase):
 def decision(self,state,elapsed=241,confirmed=False):
  return decide(elapsed=elapsed,timeout_seconds=240,evidence_state=state,restart_confirmed=confirmed)
 def test_before_timeout(self):self.assertEqual(self.decision('not-requested',239),'continue-native-probes')
 def test_request_once(self):self.assertEqual(self.decision('not-requested'),'request-history')
 def test_queued(self):self.assertEqual(self.decision('queued'),'await-history')
 def test_delivered(self):self.assertEqual(self.decision('delivered'),'await-history')
 def test_verified_restart(self):self.assertEqual(self.decision('completed',confirmed=True),'abort-systemd-restarted-native-unverified')
 def test_completed_without_restart(self):self.assertEqual(self.decision('completed'),'native-shutdown-timeout')
 def test_failed_evidence(self):self.assertEqual(self.decision('failed'),'native-shutdown-timeout')
 def test_unavailable_evidence(self):self.assertEqual(self.decision('unavailable'),'native-shutdown-timeout')
 def test_untrusted_restart_claim_ignored(self):self.assertEqual(self.decision('delivered',confirmed=True),'await-history')
 def test_never_authorizes_offline_work(self):
  for state in ('not-requested','queued','delivered','completed','failed','unavailable'):
   for confirmed in (False,True):
    self.assertNotIn(self.decision(state,confirmed=confirmed),('allow-offline-work','start'))

if __name__=='__main__':unittest.main()
