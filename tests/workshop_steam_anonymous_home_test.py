"""Verify both Workshop code paths without invoking SteamCMD or user credentials."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agents/linux/runtime'))
import content_provider_steam_workshop as workshop

class AnonymousWorkshopHomeTest(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.base=Path(tmp.name)
  self.state=self.base/'state';self.state.mkdir()
  self.auth=self.base/'authenticated';self.auth.mkdir()
  self.game_data=self.base/'game-data';self.game_data.mkdir()
  env=patch.dict(os.environ,{'CAPIVARA_AGENT_STATE_DIR':str(self.state),'CAPIVARA_STEAM_HOME':str(self.auth),'HOME':str(self.auth),'XDG_DATA_HOME':str(self.auth/'xdg'),'DSM_STEAM_USER':'real-account'})
  env.start();self.addCleanup(env.stop)
  self.private=self.state/'steam-anonymous-install-home'
 def run_download(self, *,revision=False, auth='anonymous'):
  calls=[]
  def fake_run(argv,**kwargs):
   calls.append((argv,kwargs))
   env=kwargs['env'];cache=Path(env['HOME'])/'.local/share/Steam/steamapps/workshop/content/221100/123456';cache.mkdir(parents=True,exist_ok=True)
   (cache/'payload.bin').write_bytes(b'fixture')
   return subprocess.CompletedProcess(argv,0,'Success')
  artifact={'package_id':'221100:123456','auth':auth}
  if revision: artifact['revision']='1785000000'
  # No live cache exists before the mocked download.
  with patch.object(workshop,'_steamcmd',return_value='/mock/steamcmd'),patch.object(workshop.subprocess,'run',side_effect=fake_run):
   if revision:
    # A revision needs a valid manifest; verify environment even if snapshot
    # validation rejects the fake cache afterward.
    try:workshop.materialize_steam_workshop(artifact,self.game_data,lambda p:p)
    except RuntimeError:pass
   else:
    result=workshop.resolve_steam_workshop(artifact,self.base/'stage',self.game_data)
    self.assertTrue(result.is_dir())
  self.assertEqual(len(calls),1)
  return calls[0]
 def test_anonymous_unversioned_download_private_home_and_cache(self):
  argv,kw=self.run_download()
  self.assertEqual(kw['env']['HOME'],str(self.private))
  self.assertEqual(kw['env']['CAPIVARA_STEAM_HOME'],str(self.private))
  self.assertEqual(kw['env']['XDG_DATA_HOME'],str(self.private/'.local/share'))
  self.assertEqual(self.private.stat().st_mode & 0o777,0o700)
  self.assertEqual(argv[argv.index('+login')+1],'anonymous')
 def test_anonymous_revision_path_private_home(self):
  argv,kw=self.run_download(revision=True)
  self.assertEqual(kw['env']['HOME'],str(self.private))
  self.assertEqual(argv[argv.index('+login')+1],'anonymous')
 def test_authenticated_download_retains_original_home(self):
  argv,kw=self.run_download(auth='required')
  self.assertEqual(kw['env']['HOME'],str(self.auth))
  self.assertEqual(kw['env']['CAPIVARA_STEAM_HOME'],str(self.auth))
  self.assertEqual(argv[argv.index('+login')+1],'real-account')
 def test_anonymous_symlink_rejected_before_execution(self):
  self.private.symlink_to(self.auth,target_is_directory=True)
  with patch.object(workshop,'_steamcmd',return_value='/mock/steamcmd'),patch.object(workshop.subprocess,'run') as run:
   with self.assertRaises((OSError,RuntimeError)):
    workshop.resolve_steam_workshop({'package_id':'221100:123456','auth':'anonymous'},self.base/'stage',self.game_data)
   run.assert_not_called()
if __name__=='__main__':unittest.main()
