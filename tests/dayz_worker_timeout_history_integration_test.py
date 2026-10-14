import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard/workers'))
import dayz_native_maintenance_worker_test as fixtures

class TimeoutHistoryIntegrationTest(unittest.TestCase):
 def setUp(self):
  run=fixtures.run_state()
  run['event']['native_shutdown']={'started_at':'2026-10-14T12:33:10Z','status':'waiting'}
  self.repo,self.life,self.worker=fixtures.DayZNativeMaintenanceWorkerTest().make_worker(run)
  fixtures.complete(self.life,'pre','running')
  self.now=datetime(2026,10,14,12,37,15,tzinfo=timezone.utc)
 def tick(self):return self.worker.tick(now=self.now)
 def test_history_requested_once_and_waits(self):
  first=self.tick()
  self.assertEqual(first['failed'],0)
  self.assertEqual([x['action'] for x in self.life.enqueued],['systemd_lifecycle_evidence'])
  self.assertEqual(self.repo.current['stage'],'checking-native-shutdown-history')
  second=self.tick()
  self.assertEqual(second['failed'],0)
  self.assertEqual(len(self.life.enqueued),1)
 def test_pending_evidence_expires_without_start(self):
  from datetime import timedelta
  self.tick()
  self.now+=timedelta(seconds=61)
  report=self.tick()
  self.assertEqual(report['native_shutdown_timeouts'],1)
  self.assertEqual(self.repo.finished[0]['error_code'],'native_shutdown_timeout')
  self.assertEqual([x['action'] for x in self.life.enqueued],['systemd_lifecycle_evidence'])
 def test_missing_requested_at_fails_closed(self):
  self.tick()
  del self.repo.current['event']['native_shutdown']['systemd_evidence']['requested_at']
  report=self.tick()
  self.assertEqual(report['native_shutdown_timeouts'],1)
  self.assertEqual(self.repo.finished[0]['error_code'],'native_shutdown_timeout')
 def test_no_second_history_request_on_pending(self):
  self.tick()
  for _ in range(4):self.tick()
  self.assertEqual(len(self.life.enqueued),1)
  self.assertEqual(len(self.repo.finished),0)
 def test_failed_evidence_falls_back_to_timeout(self):
  self.tick()
  self.life.states['cmd-1']['status']='failed'
  result=self.tick()
  self.assertEqual(result['native_shutdown_timeouts'],1)
  self.assertEqual(self.repo.finished[0]['error_code'],'native_shutdown_timeout')
  self.assertEqual(len(self.life.enqueued),1)
 def test_completed_untrusted_evidence_fails_closed(self):
  self.tick()
  self.life.states['cmd-1'].update({'agent_id':'wrong-agent','instance_id':'dayz-001',
   'action':'systemd_lifecycle_evidence','status':'completed',
   'parameters':{'since':'2026-10-14T12:33:10Z','until':'2026-10-14T12:37:15Z'},
   'result':{'command_id':'cmd-1','instance_id':'dayz-001',
    'action':'systemd_lifecycle_evidence','status':'completed',
    'result':{'agent_id':'wrong-agent','kind':'CapivaraSystemdLifecycleObservations',
     'scope':'instance-local','schema_version':1,'verified_native_shutdown':False,
     'instance_id':'dayz-001','events':[]}}})
  report=self.tick()
  self.assertEqual(report['native_shutdown_timeouts'],1)
  self.assertEqual(self.repo.finished[0]['error_code'],'native_shutdown_timeout')
  self.assertEqual([x['action'] for x in self.life.enqueued],['systemd_lifecycle_evidence'])
 def test_queued_then_delivered_does_not_restart(self):
  self.tick()
  self.life.states['cmd-1']['status']='delivered'
  self.assertEqual(self.tick()['failed'],0)
  self.assertEqual(len(self.life.enqueued),1)
  self.assertEqual(len(self.repo.finished),0)
 def test_historical_restart_blocks_offline_work(self):
  self.tick()
  instance='dayz-001';unit='capivara-instance-dayz-001.service'
  self.life.states['cmd-1'].update({'agent_id':'agent-001','instance_id':instance,'action':'systemd_lifecycle_evidence','status':'completed','parameters':{'since':'2026-10-14T12:33:10Z','until':'2026-10-14T12:37:15Z'},'result':{'command_id':'cmd-1','instance_id':instance,'action':'systemd_lifecycle_evidence','status':'completed','result':{'schema_version':1,'kind':'CapivaraSystemdLifecycleObservations','scope':'instance-local','instance_id':instance,'agent_id':'agent-001','verified_native_shutdown':False,'events':[{'unit':unit,'event':'stopped','at':'2026-10-14T12:36:11Z'},{'unit':unit,'event':'started','at':'2026-10-14T12:36:19Z'}]}}})
  report=self.tick()
  self.assertEqual(report['failed'],1)
  self.assertEqual(self.repo.finished[0]['error_code'],'systemd_restarted_native_unverified')
  self.assertNotIn('start',[x['action'] for x in self.life.enqueued])

if __name__=='__main__':unittest.main()
