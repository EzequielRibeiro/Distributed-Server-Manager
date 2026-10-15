import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard/workers'))
from dayz_evidence_result import authenticated_restart_observation

class EvidenceResultBindingTest(unittest.TestCase):
 def setUp(self):
  self.args=dict(agent_id='agent-1',instance_id='cli-000001-dayz-001',since='2026-10-14T12:33:10Z',until='2026-10-14T12:37:10Z')
  unit='capivara-instance-cli-000001-dayz-001.service'
  payload=dict(schema_version=1,kind='CapivaraSystemdLifecycleObservations',scope='instance-local',instance_id=self.args['instance_id'],agent_id='agent-1',verified_native_shutdown=False,events=[dict(unit=unit,event='stopped',at='2026-10-14T12:36:11Z'),dict(unit=unit,event='started',at='2026-10-14T12:36:19Z')])
  self.command=dict(command_id='cmd-1',agent_id='agent-1',instance_id=self.args['instance_id'],action='systemd_lifecycle_evidence',status='completed',parameters=dict(since=self.args['since'],until=self.args['until']),result=dict(command_id='cmd-1',instance_id=self.args['instance_id'],action='systemd_lifecycle_evidence',status='completed',result=payload))
 def check(self,command):return authenticated_restart_observation(command=command,**self.args)
 def test_valid_bound_result(self):self.assertTrue(self.check(self.command))
 def test_wrong_agent(self):self.assertFalse(self.check(dict(self.command,agent_id='other')))
 def test_wrong_action(self):self.assertFalse(self.check(dict(self.command,action='status')))
 def test_wrong_window(self):self.assertFalse(self.check(dict(self.command,parameters=dict(since='2026-10-14T12:00:00Z',until=self.args['until']))))
 def test_wrong_command_id(self):self.assertFalse(self.check(dict(self.command,result=dict(self.command['result'],command_id='other'))))
 def test_wrong_payload_agent(self):self.assertFalse(self.check(dict(self.command,result=dict(self.command['result'],result=dict(self.command['result']['result'],agent_id='other')))))
 def test_unfinished_command(self):self.assertFalse(self.check(dict(self.command,status='delivered')))
 def test_native_claim_not_accepted(self):self.assertFalse(self.check(dict(self.command,result=dict(self.command['result'],result=dict(self.command['result']['result'],verified_native_shutdown=True)))))

if __name__=='__main__':unittest.main()
