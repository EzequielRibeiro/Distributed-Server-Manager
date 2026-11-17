#!/usr/bin/env python3
"""No real SteamCMD, account, or session files are required."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'core'))
from steam_session_probe_once import classify, check_once

class SteamSessionProbeOnceTest(unittest.TestCase):
 def test_classification_reason_codes_do_not_expose_output(self):
  examples=(
   ("Logging in user 'tester' to Steam Public...OK",0,'verified'),
   ('Logged in OK',0,'verified'),
   ("Logging in user 'anonymous' to Steam Public...OK\nLogged in OK",0,'account_mismatch'),
   ('Loading Steam API...OK\nWaiting for user info...OK',0,'no_explicit_login_confirmation'),
   ("Logging in user 'tester' to Steam Public...OK\nERROR! Login Failure",0,'authentication_rejected'),
   ("Logging in user 'tester' to Steam Public...OK",1,'steamcmd_nonzero_exit'),
   ('ERROR! Login Failure: Invalid Password PASSWORD=PRIVATE',0,'authentication_rejected'),
   ('No connection / failed to connect to Steam',0,'connection_failure'),
   ('ERROR! Unknown action',0,'steamcmd_reported_error'),
   ('some private SteamCMD output',6,'steamcmd_nonzero_exit'),
  )
  for output,code,expected in examples:
   with self.subTest(expected=expected,code=code):
    got=classify(output,code,'tester')
    self.assertEqual(got,expected)
    self.assertNotIn('PRIVATE',got)

 def test_default_is_plan_only(self):
  with tempfile.TemporaryDirectory() as td:
   p=subprocess.run([sys.executable,str(ROOT/'core/steam_session_probe_once.py'),'--home',td,'--steamcmd',str(Path(td)/'missing')],capture_output=True,text=True)
   self.assertEqual(p.returncode,0)
   self.assertIn('"will_run": false',p.stdout)
 def test_one_shot_suppresses_output_and_compares_metadata(self):
  with tempfile.TemporaryDirectory() as td:
   home=Path(td)
   file=home/'.local/share/Steam/config/config.vdf';file.parent.mkdir(parents=True)
   file.write_text('PRIVATE_STEAM_TOKEN')
   calls=[]
   def fake_runner(argv,**kw):
    calls.append((argv,kw))
    file.chmod(0o600)
    return subprocess.CompletedProcess(argv,0,"Logging in user 'tester' to Steam Public...OK\nPRIVATE_STEAM_TOKEN")
   r=check_once(home/'steamcmd',home,'tester',runner=fake_runner)
   self.assertEqual(r['result'],'verified')
   self.assertEqual(len(calls),1)
   self.assertEqual(calls[0][1]['env']['HOME'],str(home))
   self.assertNotIn('XDG_DATA_HOME',calls[0][1]['env'])
   self.assertEqual(r['session_metadata']['.local/share/Steam/config/config.vdf'],'changed')
   self.assertNotIn('PRIVATE_STEAM_TOKEN',str(r))
 def test_timeout_never_discloses_credentials(self):
  with tempfile.TemporaryDirectory() as td:
   def fake_runner(*a,**kw): raise subprocess.TimeoutExpired('private_binary',75,output='SECRET')
   r=check_once(Path(td)/'steamcmd',Path(td),'tester',runner=fake_runner)
   self.assertEqual(r['result'],'timeout')
   self.assertNotIn('SECRET',str(r))

if __name__=='__main__': unittest.main()
