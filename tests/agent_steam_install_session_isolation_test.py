"""SteamCMD mocked: assert Agent anonymous installs never share authenticated HOME."""
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agents/linux/runtime'))
import game_data_executor as executor

class SteamInstallSessionIsolationTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name)
  self.state=self.base/'agent-state';self.state.mkdir()
  self.auth=self.base/'authenticated';self.auth.mkdir()
  self.install=self.base/'target'
  self.env=patch.dict(os.environ,{'CAPIVARA_AGENT_STATE_DIR':str(self.state),'HOME':str(self.auth),'CAPIVARA_STEAM_HOME':str(self.auth),'XDG_DATA_HOME':str(self.auth/'xdg'),'DSM_STEAM_USER':'test-account'})
  self.env.start();self.addCleanup(self.env.stop)
 def execute(self, auth):
  called=[]
  def fake_run(argv,**kw):
   called.append((argv,kw));return subprocess.CompletedProcess(argv,0,'')
  with patch.object(executor,'_steamcmd',return_value='/mock/steamcmd'),patch.object(executor.subprocess,'run',side_effect=fake_run):
   executor._run_steam({'provider':'steam','auth':auth,'install':{'package_id':'223350'}},self.install)
  self.assertEqual(len(called),1)
  return called[0]
 def test_anonymous_install_private_home(self):
  argv,kw=self.execute('anonymous')
  private=self.state/'steam-anonymous-install-home'
  self.assertEqual(kw['env']['HOME'],str(private))
  self.assertEqual(kw['env']['XDG_DATA_HOME'],str(private/'.local/share'))
  self.assertEqual(kw['env']['CAPIVARA_STEAM_HOME'],str(private))
  self.assertEqual(stat.S_IMODE(private.stat().st_mode),0o700)
  self.assertNotEqual(kw['env']['HOME'],str(self.auth))
  self.assertIn('anonymous',argv)
 def test_authenticated_install_keeps_existing_home(self):
  argv,kw=self.execute('required')
  self.assertEqual(kw['env']['HOME'],str(self.auth))
  self.assertEqual(kw['env']['CAPIVARA_STEAM_HOME'],str(self.auth))
  self.assertIn('test-account',argv)
  self.assertFalse((self.state/'steam-anonymous-install-home').exists())
 def test_anonymous_install_rejects_symlink_redirect(self):
  (self.state/'steam-anonymous-install-home').symlink_to(self.auth,target_is_directory=True)
  with patch.object(executor,'_steamcmd',return_value='/mock/steamcmd'),patch.object(executor.subprocess,'run') as runner:
   with self.assertRaises((RuntimeError,OSError)):executor._run_steam({'auth':'anonymous','install':{'package_id':'223350'}},self.install)
   runner.assert_not_called()
 def test_anonymous_install_rejects_world_readable_home(self):
  unsafe=self.state/'steam-anonymous-install-home';unsafe.mkdir();unsafe.chmod(0o755)
  with patch.object(executor,'_steamcmd',return_value='/mock/steamcmd'),patch.object(executor.subprocess,'run') as runner:
   with self.assertRaises(RuntimeError):executor._run_steam({'auth':'anonymous','install':{'package_id':'223350'}},self.install)
   runner.assert_not_called()
if __name__=='__main__':unittest.main()
