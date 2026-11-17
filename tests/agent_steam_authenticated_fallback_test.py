"""SteamCMD fallback policy: exactly one authenticated retry for failed anonymous installs."""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/linux/runtime"))
import game_data_executor as executor

class SteamFallbackTest(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.root=Path(tmp.name)
  self.install=self.root/"target"
  self.anonymous_home=self.root/"state"
  self.session_home=self.root/"session"
  self.session_home.mkdir()
  env=patch.dict(os.environ,{"DSM_STEAM_USER":"test-account","CAPIVARA_AGENT_STATE_DIR":str(self.anonymous_home),"CAPIVARA_STEAM_HOME":str(self.session_home),"HOME":str(self.session_home)},clear=False)
  env.start();self.addCleanup(env.stop)
  self.calls=[]
 def run_steam(self, mode, results):
  sequence=iter(results)
  def run(argv,**kwargs):
   self.calls.append((argv,kwargs))
   return next(sequence)
  with patch.object(executor,"_steamcmd",return_value="/mock/steamcmd"),patch.object(executor.subprocess,"run",side_effect=run):
   return executor._run_steam({"provider":"steam","auth":mode,"install":{"package_id":"223350"}},self.install)
 def completed(self,returncode,output):
  return subprocess.CompletedProcess(["steamcmd"],returncode,output)
 def test_anonymous_fails_then_retries_authenticated_once(self):
  self.run_steam("anonymous",[self.completed(8,"ERROR! Failed to install app (No subscription)"),self.completed(0,"Success!")])
  self.assertEqual(len(self.calls),2)
  self.assertIn("anonymous",self.calls[0][0]);self.assertIn("test-account",self.calls[1][0])
  self.assertNotEqual(self.calls[0][1]["env"]["HOME"],self.calls[1][1]["env"]["HOME"])
  self.assertEqual(self.calls[1][1]["env"]["HOME"],str(self.session_home))
  self.assertEqual(self.calls[1][1]["stdin"],subprocess.DEVNULL)
 def test_healthy_anonymous_does_not_use_authenticated_session(self):
  self.run_steam("anonymous",[self.completed(0,"Success!")])
  self.assertEqual(len(self.calls),1)
 def test_required_auth_never_attempts_anonymous(self):
  self.run_steam("required",[self.completed(0,"Success!")])
  self.assertEqual(len(self.calls),1)
  self.assertIn("test-account",self.calls[0][0])
 def test_false_steam_success_does_not_hide_timeout(self):
  with self.assertRaisesRegex(RuntimeError,"timed out"):
   self.run_steam("anonymous",[self.completed(0,"Timed out waiting for update to start, bailing. Success!"),self.completed(0,"Timed out waiting for update to start, bailing. Success!")])
  self.assertEqual(len(self.calls),2)
 def test_expired_session_error_is_not_reported_as_wrong_password(self):
  with self.assertRaisesRegex(RuntimeError,"session is missing or expired"):
   self.run_steam("anonymous",[self.completed(8,"No subscription"),self.completed(8,"Cached credentials not found. password: ERROR (Invalid Password)")])
  self.assertEqual(len(self.calls),2)
 def test_missing_authenticated_account_never_retries(self):
  with patch.dict(os.environ,{"DSM_STEAM_USER":""}),patch.object(executor,"_configured_steam_user",return_value=""):
   with self.assertRaisesRegex(RuntimeError,"configure an authenticated"):
    self.run_steam("anonymous",[self.completed(8,"No subscription")])
  self.assertEqual(len(self.calls),1)
 def test_unsupported_auth_mode_fails_closed(self):
  with self.assertRaisesRegex(RuntimeError,"unsupported Steam authentication"):
   self.run_steam("something-else",[])
  self.assertFalse(self.calls)

if __name__=="__main__":unittest.main()
