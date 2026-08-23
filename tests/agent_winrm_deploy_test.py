import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'core'),str(ROOT/'dashboard'),str(ROOT/'database')]
from agent_winrm_deploy import WinRMOptions,WinRMResult,bootstrap_windows_agent,load_winrm_profile,preflight_winrm,remote_windows_agent_present

class Runner:
 def __init__(self,outputs):self.outputs=list(outputs);self.scripts=[]
 def run_ps(self,options,script):self.scripts.append(script);return self.outputs.pop(0)

class WinRMDeployTest(unittest.TestCase):
 def test_profile_is_host_scoped(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw);(root/'node1.json').write_text(json.dumps({'port':5986,'certificate':'c.pem','private_key':'k.pem'}))
   options=load_winrm_profile('node1',root);self.assertEqual(options.endpoint,'https://node1:5986/wsman');self.assertTrue(options.certificate_pem.endswith('c.pem'))
 def test_preflight_and_presence(self):
  runner=Runner([WinRMResult(0,json.dumps({'platform':'windows','administrator':True,'architecture':'AMD64'}),''),WinRMResult(0,'ABSENT','')])
  options=WinRMOptions('node1',certificate_pem='c',private_key_pem='k')
  self.assertEqual(preflight_winrm(options,runner)['platform'],'windows');self.assertFalse(remote_windows_agent_present(options,runner))
 def test_bootstrap_uses_release_and_requires_confirmation(self):
  runner=Runner([WinRMResult(0,'BOOTSTRAP_OK','')]);options=WinRMOptions('10.0.0.8',certificate_pem='c',private_key_pem='k')
  bootstrap_windows_agent(options,controller_url='https://controller',pairing_token='one-time',release_tag='v2.1.0',runner=runner)
  self.assertIn('/agent/install.ps1',runner.scripts[0]);self.assertIn('v2.1.0',runner.scripts[0])
 def test_rejects_injection_host(self):
  with self.assertRaises(Exception):WinRMOptions('node;whoami')

if __name__=='__main__':unittest.main()
