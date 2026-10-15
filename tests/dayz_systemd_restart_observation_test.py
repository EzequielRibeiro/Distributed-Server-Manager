import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard/workers'))
from dayz_native_transition import observed_systemd_restart

class RestartObservationTest(unittest.TestCase):
    def setUp(self):
        self.args=dict(instance_id='cli-000001-dayz-001',expected_at='2026-10-14T12:33:10Z',deadline_at='2026-10-14T12:37:10Z')
        self.evidence=dict(kind='CapivaraSystemdLifecycleObservations',instance_id='cli-000001-dayz-001',verified_native_shutdown=False,events=[dict(unit='capivara-instance-cli-000001-dayz-001.service',event='stopped',at='2026-10-14T12:36:11Z'),dict(unit='capivara-instance-cli-000001-dayz-001.service',event='started',at='2026-10-14T12:36:19Z')])
    def test_real_timeline_with_authenticated_result(self):
        self.assertTrue(observed_systemd_restart(**self.args,observations=self.evidence,authenticated=True))
    def test_untrusted_result_fails(self):
        self.assertFalse(observed_systemd_restart(**self.args,observations=self.evidence))
    def test_pid_change_is_not_evidence(self):
        evidence=dict(self.evidence,events=[])
        self.assertFalse(observed_systemd_restart(**self.args,observations=evidence,authenticated=True))
    def test_outside_deadline_fails(self):
        evidence=dict(self.evidence,events=[self.evidence['events'][0],dict(self.evidence['events'][1],at='2026-10-14T12:38:00Z')])
        self.assertFalse(observed_systemd_restart(**self.args,observations=evidence,authenticated=True))
    def test_wrong_unit_fails(self):
        evidence=dict(self.evidence,events=[dict(item,unit='other.service') for item in self.evidence['events']])
        self.assertFalse(observed_systemd_restart(**self.args,observations=evidence,authenticated=True))
    def test_native_verified_claim_fails(self):
        evidence=dict(self.evidence,verified_native_shutdown=True)
        self.assertFalse(observed_systemd_restart(**self.args,observations=evidence,authenticated=True))

if __name__=='__main__':unittest.main()
