"""SteamCMD bootstrap and health probes must not touch the authenticated HOME."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agents/linux/runtime'))
import capabilities
import game_data_executor

class AnonymousSteamCmdBootstrapTest(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.base=Path(tmp.name);self.auth=self.base/'authenticated';self.auth.mkdir()
  self.state=self.base/'state';self.state.mkdir()
  p=patch.dict(os.environ,{'HOME':str(self.auth),'CAPIVARA_STEAM_HOME':str(self.auth),'XDG_DATA_HOME':str(self.auth/'xdg'),'CAPIVARA_AGENT_STATE_DIR':str(self.state)})
  p.start();self.addCleanup(p.stop)
 def test_capability_probe_uses_isolated_home_and_redacts_raw_error(self):
  binary=self.base/'steamcmd';binary.write_text('mock')
  recorded=[]
  def runner(argv,**kwargs):
   recorded.append(kwargs['env'])
   return subprocess.CompletedProcess(argv,27,'ACCOUNT_SECRET_DO_NOT_EXPOSE')
  with patch.object(capabilities.shutil,'which',return_value=str(binary)),patch.object(capabilities,'platform') as plat,patch.object(capabilities.subprocess,'run',side_effect=runner):
   plat.machine.return_value='i686'
   result=capabilities._steamcmd_status()
  self.assertEqual(len(recorded),1)
  env=recorded[0];private=self.state/'steam-anonymous-metadata-home'
  self.assertEqual(env['HOME'],str(private))
  self.assertEqual(env['CAPIVARA_STEAM_HOME'],str(private))
  self.assertEqual(env['XDG_DATA_HOME'],str(private/'.local/share'))
  self.assertNotIn('ACCOUNT_SECRET',str(result))
  self.assertFalse(result['functional'])
 def test_steamcmd_install_bootstrap_uses_isolated_home(self):
  recorded=[]
  def fake_download(url,destination): destination.write_bytes(b'fixture')
  def fake_extract(archive,dest):
   (dest/'steamcmd.sh').write_text('mock')
  def runner(argv,**kwargs):
   recorded.append(kwargs['env']);return subprocess.CompletedProcess(argv,0,'OK')
  with patch.object(game_data_executor,'_download',side_effect=fake_download),patch.object(game_data_executor,'_extract_tar',side_effect=fake_extract),patch.object(game_data_executor.subprocess,'run',side_effect=runner):
   result=game_data_executor._install_steamcmd()
  self.assertTrue(result['functional'])
  self.assertEqual(len(recorded),1)
  private=self.state/'steam-anonymous-metadata-home';env=recorded[0]
  self.assertEqual(env['HOME'],str(private))
  self.assertEqual(env['XDG_DATA_HOME'],str(private/'.local/share'))
  self.assertNotEqual(env['HOME'],str(self.auth))
 def test_capability_probe_rejects_symlink_before_launch(self):
  binary=self.base/'steamcmd';binary.write_text('mock')
  (self.state/'steam-anonymous-metadata-home').symlink_to(self.auth,target_is_directory=True)
  with patch.object(capabilities.shutil,'which',return_value=str(binary)),patch.object(capabilities,'platform') as plat,patch.object(capabilities.subprocess,'run') as run:
   plat.machine.return_value='i686'
   result=capabilities._steamcmd_status()
   run.assert_not_called()
  self.assertFalse(result['functional'])
  self.assertNotIn(str(self.auth),str(result))
if __name__=='__main__':unittest.main()
