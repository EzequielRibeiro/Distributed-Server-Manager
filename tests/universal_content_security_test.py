#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,json,os,stat,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

def load(path:Path,name:str):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);assert spec.loader;spec.loader.exec_module(module);return module

class UniversalContentSecurityTest(unittest.TestCase):
 def fake_scanner(self,root:Path)->tuple[Path,Path]:
  rules=root/'rules';rules.mkdir();(rules/'baseline.yar').write_text('rule baseline { condition: false }\n')
  binary=root/'yr';binary.write_text('''#!/usr/bin/env python3\nimport json,sys\ntarget=sys.argv[-1]\nif "scan-fail" in target:\n print("scanner failed",file=sys.stderr);raise SystemExit(2)\nif "blocked" in target:\n print(json.dumps({"path":target,"rules":[{"identifier":"known_malware","tags":["malware"]}]}))\nelif "suspicious" in target:\n print(json.dumps({"path":target,"rules":[{"identifier":"review_me","tags":["review"]}]}))\n''');binary.chmod(binary.stat().st_mode|stat.S_IXUSR)
  return binary,rules
 def test_yarax_verdicts_are_platform_neutral_and_fail_closed(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);binary,rules=self.fake_scanner(root)
   env={"CAPIVARA_AGENT_STATE_DIR":str(root/'state'),"CAPIVARA_YARAX_BIN":str(binary),"CAPIVARA_YARAX_RULES_PATH":str(rules)}
   with patch.dict(os.environ,env,clear=False):
    for platform in ('linux','windows'):
     module=load(ROOT/f'agents/{platform}/runtime/content_security.py',f'u7_security_{platform}_{id(self)}')
     self.assertTrue(module.scanner_status()['ready'])
     for name,state in (("clean.jar","clean"),("suspicious.jar","suspicious"),("blocked.jar","blocked"),("scan-fail.jar","scan_failed")):
      target=root/name;target.write_bytes(b'x');self.assertEqual(module.scan_content(target)['security_state'],state)
 def test_missing_engine_or_rules_is_scan_failed(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);target=root/'content.jar';target.write_bytes(b'x')
   with patch.dict(os.environ,{"CAPIVARA_AGENT_STATE_DIR":str(root/'state'),"CAPIVARA_YARAX_BIN":str(root/'missing'),"CAPIVARA_YARAX_RULES_PATH":str(root/'rules')},clear=False):
    module=load(ROOT/'agents/linux/runtime/content_security.py',f'u7_missing_{id(self)}');self.assertFalse(module.scanner_status()['ready']);self.assertEqual(module.scan_content(target)['security_state'],'scan_failed')
 def test_directory_scan_is_recursive_and_symlink_tree_is_blocked(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);binary,rules=self.fake_scanner(root);tree=root/'payload';(tree/'nested').mkdir(parents=True);(tree/'nested'/'clean.jar').write_bytes(b'x')
   seen=[]
   env={"CAPIVARA_AGENT_STATE_DIR":str(root/'state'),"CAPIVARA_YARAX_BIN":str(binary),"CAPIVARA_YARAX_RULES_PATH":str(rules)}
   with patch.dict(os.environ,env,clear=False):
    module=load(ROOT/'agents/linux/runtime/content_security.py',f'u7_recursive_{id(self)}')
    original=module.subprocess.run
    def capture(args,**kwargs):seen.extend(args);return original(args,**kwargs)
    with patch.object(module.subprocess,'run',side_effect=capture):self.assertEqual(module.scan_content(tree)['security_state'],'clean')
    self.assertIn('--recursive',seen);self.assertIn('--timeout',seen)
    outside=root/'outside';outside.mkdir();link=tree/'escape'
    try:link.symlink_to(outside,target_is_directory=True)
    except (OSError,NotImplementedError):return
    with patch.object(module.subprocess,'run') as runner:
     result=module.scan_content(tree)
    self.assertEqual(result['security_state'],'blocked');runner.assert_not_called()
 def test_activation_requires_clean_under_u7_but_grandfathers_legacy_state(self):
  module=load(ROOT/'agents/linux/runtime/content_activation_projection.py',f'u7_projection_{id(self)}')
  base={"status":"applied","desired_state":"installed","activation_state":"enabled","installed_version":"1","content_id":"mod","managed_path":"/tmp/mod"}
  self.assertIsNotNone(module._entry(dict(base)))
  self.assertIsNotNone(module._entry({**base,"security_policy_version":1,"security_state":"clean"}))
  for state in ("unscanned","suspicious","blocked","scan_failed"):
   with self.subTest(state=state):self.assertIsNone(module._entry({**base,"security_policy_version":1,"security_state":state}))
 def test_rejected_candidate_preserves_prior_clean_applied_projection(self):
  for platform in ("linux","windows"):
   with self.subTest(platform=platform):
    module=load(ROOT/f'agents/{platform}/runtime/content_activation_projection.py',f'u10_projection_{platform}_{id(self)}')
    base={"desired_state":"installed","activation_state":"enabled","installed_version":"1","content_id":"mod","managed_path":"/tmp/mod","security_policy_version":1,"applied_revision":4,"applied_checksum":"a"*64,"applied_security_state":"clean"}
    for status,desired_security in (("security_blocked","blocked"),("security_scan_failed","scan_failed")):
     entry=module._entry({**base,"status":status,"security_state":desired_security})
     self.assertIsNotNone(entry);self.assertEqual(entry["content_id"],"mod")
    self.assertIsNone(module._entry({**base,"status":"security_blocked","security_state":"blocked","applied_security_state":"unscanned"}))
    self.assertIsNone(module._entry({**base,"status":"security_blocked","security_state":"blocked","applied_revision":None,"applied_checksum":None}))

if __name__=='__main__':unittest.main()
