#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,os,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load(path,name,env_name):
 old=os.environ.get(env_name)
 try:
  temp=tempfile.TemporaryDirectory();os.environ[env_name]=temp.name
  spec=importlib.util.spec_from_file_location(name,ROOT/path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  return module,temp,old
 except Exception:
  if old is None:os.environ.pop(env_name,None)
  else:os.environ[env_name]=old
  raise

class AgentUploadConfinementTest(unittest.TestCase):
 def _check(self,path,name,env_name):
  module,temp,old=load(path,name,env_name)
  try:
   destination=module._content_upload_destination("i1","transfer-1","mod.zip")
   destination.relative_to(Path(temp.name).resolve());self.assertEqual(destination.name,"mod.zip")
   self.assertIn("content-uploads",destination.parts)
   with self.assertRaises(ValueError):module._content_upload_destination("../i1","transfer-1","mod.zip")
   with self.assertRaises(ValueError):module._content_upload_destination("i1","../transfer","mod.zip")
   with self.assertRaises(ValueError):module._content_upload_destination("i1","transfer-1","bad\nname.zip")
  finally:
   temp.cleanup()
   if old is None:os.environ.pop(env_name,None)
   else:os.environ[env_name]=old
 def test_linux_destination_is_confined(self):self._check(Path("agents/linux/runtime/artifact_transfer_client.py"),"linux_artifact_transfer","CAPIVARA_GAME_DATA_ROOT")
 def test_windows_destination_is_confined(self):self._check(Path("agents/windows/runtime/artifact_transfer_client.py"),"windows_artifact_transfer","CAPIVARA_AGENT_GAME_DATA_ROOT")

if __name__=="__main__":unittest.main()
