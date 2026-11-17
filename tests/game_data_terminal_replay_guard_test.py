"""Terminal game-data job replays cannot call update state handlers again."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'database'))
from agent_game_data_repository import AgentGameDataRepository

class TerminalReplayGuardTest(unittest.TestCase):
 def test_terminal_job_replay_does_not_dispatch_server_update(self):
  backend=MagicMock();backend.name='sqlite';repo=AgentGameDataRepository(backend)
  job={'job_id':'old','agent_id':'agent','action':'verify','status':'completed','progress':100,'selection':{'_server_update':{'instance_id':'dayz','operation':'check'}}}
  repo.snapshot=MagicMock(return_value=job)
  class Session:
   def execute(self,*args,**kwargs):return MagicMock(rowcount=0)
  from contextlib import contextmanager
  @contextmanager
  def session(*args,**kwargs):yield Session()
  repo.session=session
  with patch('server_update_repository.ServerUpdateRepository') as updates:
   result=repo.apply_result('agent',{'job_id':'old','status':'completed','progress':100})
   self.assertEqual(result,job)
   updates.assert_not_called()
if __name__=='__main__':unittest.main()
