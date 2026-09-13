#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,json,os,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def _load(path:Path,name:str,state:Path):
 os.environ["CAPIVARA_AGENT_STATE_DIR"]=str(state)
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def _state(root:Path,instance:str,content:str,**overrides):
 payload={"instance_id":instance,"content_id":content,"status":"applied","desired_state":"installed","activation_state":"enabled","activation_order":0,"installed_version":"1","game_id":"dayz","content_type":"workshop","provider":"steam-workshop","package_id":"221100:123","target":f"workshop/{content}","managed_path":f"/srv/content/{content}","activation":{"mode":"mod"}};payload.update(overrides);path=root/"managed-content"/instance/f"{content}.json";path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(payload),encoding="utf-8")

class ActivationProjectionTest(unittest.TestCase):
 def _exercise(self,module_path:Path,name:str):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);module=_load(module_path,name,root)
   _state(root,"i1","z-last",activation_order=20)
   _state(root,"i1","a-first",activation_order=10)
   _state(root,"i1","b-tie",activation_order=10)
   _state(root,"i1","disabled",activation_state="disabled",activation_order=1)
   _state(root,"i1","absent",desired_state="absent",installed_version=None)
   _state(root,"i1","failed",status="failed")
   snapshot=module.refresh_activation_snapshot("i1")
   self.assertEqual(snapshot["kind"],"CapivaraContentActivationSnapshot")
   self.assertEqual([x["content_id"] for x in snapshot["entries"]],["a-first","b-tie","z-last"])
   self.assertEqual(snapshot["entries"][0]["activation"],{"mode":"mod"})
   self.assertEqual(module.activation_snapshot("i1")["checksum"],snapshot["checksum"])
   before=snapshot["checksum"];_state(root,"i1","a-first",activation_order=30);after=module.refresh_activation_snapshot("i1")
   self.assertNotEqual(before,after["checksum"]);self.assertEqual([x["content_id"] for x in after["entries"]],["b-tie","z-last","a-first"])
 def test_linux_projection(self):self._exercise(ROOT/"agents/linux/runtime/content_activation_projection.py","linux_content_activation_projection")
 def test_windows_projection(self):self._exercise(ROOT/"agents/windows/runtime/content_activation_projection.py","windows_content_activation_projection")

if __name__=="__main__":unittest.main()
