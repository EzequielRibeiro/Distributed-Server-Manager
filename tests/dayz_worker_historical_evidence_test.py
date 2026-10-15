"""Unit tests for historical evidence classification; no live services."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard/workers'))
from maintenance_worker import MaintenanceWorker

class HistoricalEvidenceWorkerTest(unittest.TestCase):
 def setUp(self):
  self.instance='cli-000001-dayz-001'
  self.run={'instance_id':self.instance,'agent_id':'agent-1'}
  self.state={'systemd_evidence':{'command_id':'cmd-1','since':'2026-10-14T12:33:10Z','until':'2026-10-14T12:37:10Z'}}
  unit=f'capivara-instance-{self.instance}.service'
  self.command={'command_id':'cmd-1','instance_id':self.instance,'agent_id':'agent-1','action':'systemd_lifecycle_evidence','status':'completed','parameters':{'since':self.state['systemd_evidence']['since'],'until':self.state['systemd_evidence']['until']},'result':{'command_id':'cmd-1','instance_id':self.instance,'action':'systemd_lifecycle_evidence','status':'completed','result':{'schema_version':1,'kind':'CapivaraSystemdLifecycleObservations','scope':'instance-local','instance_id':self.instance,'agent_id':'agent-1','verified_native_shutdown':False,'events':[{'event':'stopped','unit':unit,'at':'2026-10-14T12:36:11Z'},{'event':'started','unit':unit,'at':'2026-10-14T12:36:19Z'}]}}}
  self.worker=object.__new__(MaintenanceWorker)
  self.worker._command=lambda command_id:self.command if command_id=='cmd-1' else None
 def test_bound_systemd_restart(self):
  self.assertTrue(self.worker._historical_restart_confirmed(self.run,self.state))
 def test_missing_evidence(self):
  self.assertFalse(self.worker._historical_restart_confirmed(self.run,{}))
 def test_wrong_agent(self):
  self.command['agent_id']='agent-2'
  self.assertFalse(self.worker._historical_restart_confirmed(self.run,self.state))
 def test_unfinished_result(self):
  self.command['status']='delivered'
  self.assertFalse(self.worker._historical_restart_confirmed(self.run,self.state))
 def test_missing_repository_command(self):
  self.worker._command=lambda command_id:None
  self.assertFalse(self.worker._historical_restart_confirmed(self.run,self.state))
 def test_wrong_window(self):
  self.state['systemd_evidence']['until']='2026-10-14T12:40:00Z'
  self.assertFalse(self.worker._historical_restart_confirmed(self.run,self.state))

if __name__=='__main__':unittest.main()
