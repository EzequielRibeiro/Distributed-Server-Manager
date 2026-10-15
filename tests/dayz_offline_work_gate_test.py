import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard/workers'))
from dayz_native_transition import offline_work_gate

class OfflineWorkGateTest(unittest.TestCase):
    def test_fresh_stopped_allows_offline_work(self):
        self.assertEqual(offline_work_gate(latest_status='stopped',status_completed=True),'allow-offline-work')
    def test_running_blocks(self):
        self.assertEqual(offline_work_gate(latest_status='running',status_completed=True),'abort-instance-active')
    def test_starting_blocks(self):
        self.assertEqual(offline_work_gate(latest_status='starting',status_completed=True),'abort-instance-active')
    def test_historical_restart_blocks_even_if_stopped_probe(self):
        self.assertEqual(offline_work_gate(latest_status='stopped',status_completed=True,historical_restart=True),'abort-already-restarted')
    def test_stale_stopped_probe_not_accepted(self):
        self.assertEqual(offline_work_gate(latest_status='stopped',status_completed=False),'wait-for-fresh-status')
    def test_unavailable_is_not_stopped(self):
        self.assertEqual(offline_work_gate(latest_status='unavailable',status_completed=True),'wait-for-fresh-status')
    def test_missing_state_is_not_stopped(self):
        self.assertEqual(offline_work_gate(latest_status=None,status_completed=True),'wait-for-fresh-status')

if __name__=='__main__':unittest.main()
