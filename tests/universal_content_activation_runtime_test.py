#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def _load(path:Path,name:str):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class ContentActivationRuntimeTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.module=_load(ROOT/"agents/linux/runtime/content_activation_runtime.py","content_activation_runtime_tested")
 def _spec(self,root:Path):
  return {"instance_id":"i1","arguments":["-config=server.cfg"],"working_directory":str(root/"server"),"instance_state_root":str(root/"state")}
 def test_dayz_projection_uses_managed_paths_and_preserves_base_arguments(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/"server").mkdir();mod_a=root/"state"/"content"/"a";mod_b=root/"state"/"content"/"b";mod_a.mkdir(parents=True);mod_b.mkdir(parents=True)
   snapshot={"checksum":"abc","entries":[
    {"content_id":"a","game_id":"dayz","package_id":"221100:111","managed_path":str(mod_a),"activation":{"mode":"mod"}},
    {"content_id":"b","game_id":"dayz","package_id":"221100:222","managed_path":str(mod_b),"activation":{"mode":"server-mod"}},
   ]}
   projected=self.module.project_runtime_spec(self._spec(root),snapshot)
   self.assertEqual(projected["content_base_arguments"],["-config=server.cfg"])
   self.assertEqual(projected["arguments"],["-config=server.cfg","-mod=@dsm-i1-111","-serverMod=@dsm-i1-222"])
   self.assertEqual([item["alias"] for item in projected["content_dayz_mod_aliases"]],["@dsm-i1-111","@dsm-i1-222"])
   self.assertEqual(projected["content_activation_checksum"],"abc")
   empty=self.module.project_runtime_spec(projected,{"checksum":"empty","entries":[]})
   self.assertEqual(empty["arguments"],["-config=server.cfg"])
   self.assertNotIn("content_dayz_mod_aliases",empty)
 def test_dayz_map_projection_exposes_missions_without_adding_mod_argument(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/"server").mkdir();mission=root/"state"/"content"/"maps"/"namalsk"/"Mission Files"/"regular.namalsk";(mission/"db").mkdir(parents=True)
   (mission/"init.c").write_text("void main() {}\n",encoding="utf-8");(mission/"db"/"types.xml").write_text("<types/>\n",encoding="utf-8")
   spec={**self._spec(root),"game_id":"dayz"}
   snapshot={"checksum":"map","entries":[{"content_id":"github:namalsk","game_id":"dayz","content_type":"map","provider":"github","managed_path":str(root/"state"/"content"/"maps"/"namalsk")}]}
   projected=self.module.project_runtime_spec(spec,snapshot)
   self.assertEqual(projected["arguments"],["-config=server.cfg"])
   self.assertNotIn("content_dayz_mod_aliases",projected)
   self.assertEqual(projected["content_dayz_community_missions"],[{"id":"regular.namalsk","source":str(mission.resolve()),"content_id":"github:namalsk"}])
 def test_project_zomboid_projection_and_materialization(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/"server").mkdir();(root/"state").mkdir()
   snapshot={"checksum":"pz","entries":[
    {"content_id":"a","game_id":"projectzomboid","package_id":"108600:111","activation":{"identifier":"Alpha"}},
    {"content_id":"b","game_id":"projectzomboid","package_id":"108600:222","activation":{"identifier":"Beta"}},
   ]}
   projected=self.module.project_runtime_spec(self._spec(root),snapshot)
   self.assertEqual(projected["arguments"],["-config=server.cfg"])
   props=projected["content_configuration_properties"]
   self.assertEqual([p["key"] for p in props],["WorkshopItems","Mods"])
   written=self.module.materialize_content_activation(projected)
   self.assertEqual(written,["Zomboid/Server/servertest.ini","Zomboid/Server/servertest.ini"])
   text=(root/"state"/"Zomboid"/"Server"/"servertest.ini").read_text(encoding="utf-8")
   self.assertIn("WorkshopItems=111;222",text);self.assertIn("Mods=Alpha;Beta",text)
   self.module.materialize_content_activation(projected)
   text2=(root/"state"/"Zomboid"/"Server"/"servertest.ini").read_text(encoding="utf-8")
   self.assertEqual(text,text2)
 def test_cross_game_or_invalid_adapter_fails_closed(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/"server").mkdir()
   with self.assertRaises(self.module.ContentRuntimeActivationError):self.module.project_runtime_spec(self._spec(root),{"checksum":"x","entries":[{"content_id":"a","game_id":"dayz","managed_path":"/tmp/a","activation":{"adapter":"project-zomboid"}}]})
   with self.assertRaises(self.module.ContentRuntimeActivationError):self.module.project_runtime_spec(self._spec(root),{"checksum":"x","entries":[{"content_id":"a","game_id":"projectzomboid","package_id":"221100:1","activation":{"identifier":"A"}}]})

if __name__=="__main__":unittest.main()