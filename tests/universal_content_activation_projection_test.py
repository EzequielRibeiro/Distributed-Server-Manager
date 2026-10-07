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
   _state(root,"maps","dayz-map:deerisle",content_type="map",activation_state="disabled",community_map={"name":"Deer Isle","mission_path":"V5.9/empty.deerisle"})
   map_snapshot=module.activation_snapshot_with("maps",["dayz-map:deerisle"])
   self.assertEqual(map_snapshot["entries"][0]["metadata"]["community_map"],{"name":"Deer Isle","mission_path":"V5.9/empty.deerisle"})
   _state(root,"unsafe-map","dayz-map:unsafe",content_type="map",community_map={"name":"Unsafe","mission_path":"../empty.deerisle"})
   with self.assertRaisesRegex(ValueError,"invalid DayZ community mission path"):
    module.refresh_activation_snapshot("unsafe-map")
   before=snapshot["checksum"];_state(root,"i1","a-first",activation_order=30);after=module.refresh_activation_snapshot("i1")
   self.assertNotEqual(before,after["checksum"]);self.assertEqual([x["content_id"] for x in after["entries"]],["b-tie","z-last","a-first"])

   _state(root,"deps","vpp",activation_order=0,dependencies=["cf"])
   blocked=module.refresh_activation_snapshot("deps")
   self.assertEqual(blocked["entries"],[])
   _state(root,"deps","cf",activation_order=99)
   ordered=module.refresh_activation_snapshot("deps")
   self.assertEqual([x["content_id"] for x in ordered["entries"]],["cf","vpp"])

   commands=[
    {"instance_id":"i1","content_id":"b-tie","desired_state":"installed","activation_state":"disabled","activation_order":99,"metadata":{"activation":{"adapter":"dayz","mode":"server-mod","identifier":"safe-id","command":"rm -rf /"}}},
    {"instance_id":"i1","content_id":"z-last","desired_state":"installed","activation_state":"enabled","activation_order":1,"dependencies":["a-first"],"metadata":{"activation":{"adapter":"dayz","mode":"mod"}}},
   ]
   reports=[
    {"instance_id":"i1","content_id":"b-tie","status":"applied"},
    {"instance_id":"i1","content_id":"z-last","status":"applied"},
   ]
   synced=module.synchronize_activation_state(commands,reports)
   self.assertEqual(len(synced),1)
   self.assertEqual([x["content_id"] for x in synced[0]["entries"]],["a-first","z-last"])
   self.assertEqual(synced[0]["entries"][1]["activation"],{"adapter":"dayz","mode":"mod"})
   stored=json.loads((root/"managed-content"/"i1"/"b-tie.json").read_text(encoding="utf-8"))
   self.assertEqual(stored["activation_state"],"disabled")
   self.assertEqual(stored["activation_order"],99)
   self.assertEqual(stored["activation"],{"adapter":"dayz","mode":"server-mod","identifier":"safe-id"})
   zstored=json.loads((root/"managed-content"/"i1"/"z-last.json").read_text(encoding="utf-8"))
   self.assertEqual(zstored["dependencies"],["a-first"])
   self.assertNotIn("command",stored["activation"])
 def test_linux_projection(self):self._exercise(ROOT/"agents/linux/runtime/content_activation_projection.py","linux_content_activation_projection")
 def test_windows_projection(self):self._exercise(ROOT/"agents/windows/runtime/content_activation_projection.py","windows_content_activation_projection")

if __name__=="__main__":unittest.main()

class DayZConfiguredMapDependencyProjectionTest(unittest.TestCase):
 def test_disabled_dayz_content_reincludes_configured_map_dependency(self):
  import tempfile,os,json
  old=os.environ.get('CAPIVARA_AGENT_STATE_DIR')
  with tempfile.TemporaryDirectory() as tmp:
   os.environ['CAPIVARA_AGENT_STATE_DIR']=tmp
   module=_load(ROOT/'agents/linux/runtime/content_activation_projection.py','dayz_required_projection_tested',Path(tmp))
   iid='i1';root=Path(tmp)/'instance';(root/'config').mkdir(parents=True)
   (root/'config'/'serverDZ.cfg').write_text('class Missions { class DayZ { template="empty.deerisle"; }; };\n')
   state=Path(tmp)/'managed-content'/iid;state.mkdir(parents=True)
   mission=root/'content/maps/deer/V5.9/empty.deerisle';mission.mkdir(parents=True);(mission/'init.c').write_text('// test');(mission/'cfgeconomycore.xml').write_text('<economy/>')
   (state/'dayz-map:deerisle.json').write_text(json.dumps({'content_id':'dayz-map:deerisle','game_id':'dayz','content_type':'map','desired_state':'installed','status':'applied','installed_version':'latest','security_state':'clean','managed_path':str(root/'content/maps/deer'),'dependencies':['steam-workshop:1602372402'],'community_map':{'mission_path':'V5.9/empty.deerisle'}}))
   (state/'steam-workshop:1602372402.json').write_text(json.dumps({'content_id':'steam-workshop:1602372402','game_id':'dayz','content_type':'workshop','desired_state':'installed','status':'applied','installed_version':'1','security_state':'clean','managed_path':str(root/'content/workshop/deer'),'package_id':'221100:1602372402','activation':{'adapter':'dayz','mode':'mod'}}))
   base={'schema_version':1,'kind':'CapivaraContentActivationSnapshot','instance_id':iid,'entries':[],'checksum':'disabled-only'}
   enriched=module.activation_snapshot_for_runtime(iid,{'game_id':'dayz','dayz_content_enabled':False,'instance_state_root':str(root)},base)
   ids=[e['content_id'] for e in enriched['entries']]
   self.assertEqual(ids,['steam-workshop:1602372402','dayz-map:deerisle'])
   prepared,enriched2=module.runtime_projection_inputs(iid,{'game_id':'dayz','dayz_content_enabled':False,'instance_state_root':str(root)},base)
   self.assertEqual(prepared['dayz_required_content_ids'],['steam-workshop:1602372402'])
   self.assertEqual([e['content_id'] for e in enriched2['entries']],['steam-workshop:1602372402','dayz-map:deerisle'])
  if old is None:os.environ.pop('CAPIVARA_AGENT_STATE_DIR',None)
  else:os.environ['CAPIVARA_AGENT_STATE_DIR']=old
