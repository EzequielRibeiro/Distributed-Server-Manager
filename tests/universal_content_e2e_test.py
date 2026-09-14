#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HARNESS=ROOT/'tests'/'universal_content_e2e_harness.py'

def _expected():
 return {
  'paper_blocked_payload':'paper-a-p1-v1',
  'paper_b_payload':'paper-b-v1',
  'neo_payload':'neo-mod-v1',
  'neo_side_payload':'neo-side-v1',
  'pack_a_payload':'pack-a-v1',
  'upload_payload':'external-upload',
 }


class UniversalContentE2ETest(unittest.TestCase):
 def _run(self,platform):
  with tempfile.TemporaryDirectory() as tmp:
   output=Path(tmp)/'summary.json';env=os.environ.copy()
   cp=subprocess.run([sys.executable,str(HARNESS),'--platform',platform,'--work-root',str(Path(tmp)/'work'),'--output',str(output)],cwd=str(ROOT),env=env,capture_output=True,text=True,check=False,timeout=180)
   self.assertEqual(cp.returncode,0,cp.stdout+'\n'+cp.stderr);self.assertTrue(output.is_file());return json.loads(output.read_text())
 def test_representative_matrix(self):
  forced=str(os.environ.get('CAPIVARA_U10_PLATFORM') or '').strip().lower();platforms=[forced] if forced else ['linux','windows'];expected=_expected();summaries=[]
  for platform in platforms:
   with self.subTest(platform=platform):
    result=self._run(platform);summaries.append(result)
    self.assertEqual(result['paper_order'],['p1','p2']);self.assertIsNotNone(result['paper_rollback_version']);self.assertEqual(result['blocked_state'],'blocked');self.assertTrue(result['isolation'])
    self.assertEqual(result['neo_order'],['mod-side','mod-main']);self.assertEqual(result['pack_revision'],3);self.assertFalse(result['pack_b_present']);self.assertEqual(result['pack_config'],'layer=server-v1\n')
    for key,value in expected.items():self.assertEqual(result[key],value,key)
  if len(summaries)==2:
   left={k:v for k,v in summaries[0].items() if k!='platform'};right={k:v for k,v in summaries[1].items() if k!='platform'};self.assertEqual(left,right)
 def test_u5_dayz_project_zomboid_regressions_remain_gated(self):
  workflow=(ROOT/'.github/workflows/universal-content.yml').read_text(encoding='utf-8');self.assertIn('tests/universal_content_activation_runtime_test.py',workflow)
  source=(ROOT/'tests/universal_content_activation_runtime_test.py').read_text(encoding='utf-8').lower();self.assertIn('dayz',source);self.assertIn('projectzomboid',source)
if __name__=='__main__':unittest.main()
