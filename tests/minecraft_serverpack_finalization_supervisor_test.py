"""No game servers. Asynchronous spawn, retry and heartbeat isolation."""
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock

R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/"agents/linux/runtime"))
from minecraft_serverpack_finalization_supervisor import FinalizationWorkerSupervisor

class SupervisorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.now=[1000.0]
  self.proc=Mock()
  self.proc.poll.return_value=None
  self.spawn=Mock(return_value=self.proc)
  self.supervisor=FinalizationWorkerSupervisor(clock=lambda:self.now[0],spawn=self.spawn)
 def launch(self,**kwargs):
  return self.supervisor.launch(instance_id="pr855-disposable",config_path=self.root/"agent.json",
                                state_dir=self.root,**kwargs)
 def test_spawns_worker_nonblocking(self):
  self.assertEqual(self.launch(),"started")
  self.assertEqual(self.spawn.call_count,1)
  self.assertTrue(self.spawn.call_args.kwargs["start_new_session"])
  self.assertEqual(self.spawn.call_args.args[0][2],str(self.root/"agent.json"))
  self.assertEqual(self.spawn.call_args.args[0][3],"pr855-disposable")
 def test_does_not_spawn_two_running_workers(self):
  self.assertEqual(self.launch(),"started")
  self.assertEqual(self.launch(),"already_running")
  self.assertEqual(self.spawn.call_count,1)
 def test_worker_exit_cooldown_prevents_spin(self):
  self.launch();self.proc.poll.return_value=1
  self.assertEqual(self.launch(),"cooldown")
  self.assertEqual(self.spawn.call_count,1)
  self.now[0]+=121
  self.assertEqual(self.launch(),"started")
  self.assertEqual(self.spawn.call_count,2)
 def test_bad_identity_rejected(self):
  with self.assertRaises(ValueError):
   self.supervisor.launch(instance_id="../../test",config_path=self.root/"a",state_dir=self.root)
  self.assertEqual(self.spawn.call_count,0)
 def test_symlink_log_rejected(self):
  folder=self.root/"finalization-worker";folder.mkdir()
  (folder/"pr855-disposable.log").symlink_to(self.root/"target")
  with self.assertRaises(RuntimeError):self.launch()
  self.assertEqual(self.spawn.call_count,0)
 def test_does_not_put_credentials_in_process_args(self):
  self.launch()
  args=self.spawn.call_args.args[0]
  self.assertEqual(len(args),4)
  self.assertNotIn("password",str(args).lower())

if __name__=="__main__":unittest.main()
