"""Worker integration regression: no production services are touched."""
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from dayz_native_maintenance_worker_test import DayZNativeMaintenanceWorkerTest,run_state,complete

NOW=datetime(2026,9,16,15,0,5,tzinfo=timezone.utc)
class NativeOfflineGateIntegrationTest(unittest.TestCase):
 def setUp(self):
  run=run_state()
  self.repo,self.life,self.worker=DayZNativeMaintenanceWorkerTest().make_worker(run)
  complete(self.life,'pre','stopped')
  self.applied=[]
  self.worker._apply_game_work=lambda *a:(self.applied.append('game') or (a[1],True))
  self.worker._apply_content_work=lambda *a:(self.applied.append('content') or (a[1],True))
  self.worker._prepare_next_native_restart=lambda run,event,now,result:(event,False)
 def test_initial_stopped_probe_requires_fresh_check(self):
  self.worker.tick(now=NOW)
  self.assertEqual([x['action'] for x in self.life.enqueued],['status'])
  self.assertEqual(self.applied,[])
  self.assertEqual(self.repo.current['status'],'running')
 def test_restarted_instance_blocks_work_and_second_start(self):
  self.worker.tick(now=NOW)
  complete(self.life,'cmd-1','running')
  self.worker.tick(now=NOW)
  self.assertEqual(self.applied,[])
  self.assertEqual(self.repo.finished[-1]['error_code'],'native_offline_state_active')
  self.assertNotIn('start',[x['action'] for x in self.life.enqueued])
 def test_fresh_stopped_status_permits_offline_stage(self):
  self.worker.tick(now=NOW)
  complete(self.life,'cmd-1','stopped')
  self.worker.tick(now=NOW)
  self.assertEqual(self.applied,['game','content'])
  self.assertEqual(self.repo.current['status'],'running')

if __name__=='__main__':unittest.main()
