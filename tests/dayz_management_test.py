#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/"agents"/"common"
if str(COMMON) not in sys.path:sys.path.insert(0,str(COMMON))
from dayz_management import apply_mission,current_mission,discover_missions,mod_compatibility_preflight,wipe

class DayZManagementTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.game=self.root/"game";self.state=self.root/"state"
  (self.game/"mpmissions"/"dayzOffline.chernarusplus").mkdir(parents=True)
  (self.game/"mpmissions"/"dayzOffline.enoch").mkdir(parents=True)
  (self.state/"config").mkdir(parents=True)
  (self.state/"mpmissions"/"dayzOffline.chernarusplus"/"storage_1").mkdir(parents=True)
  (self.state/"mpmissions"/"dayzOffline.chernarusplus"/"storage_1"/"players.db").write_text("state",encoding="utf-8")
  (self.state/"config"/"serverDZ.cfg").write_text('class Missions { class DayZ { template="dayzOffline.chernarusplus"; }; };\n',encoding="utf-8")
  self.record={"instance_id":"dayz-1","agent_id":"agent-1","game_id":"dayz","adapter":"systemd","working_directory":str(self.game),"instance_state_root":str(self.state),"config_path":str(self.state/"config"/"serverDZ.cfg"),"arguments":["-config="+str(self.state/"config"/"serverDZ.cfg")],"bind_paths":[{"source":str(self.state/"mpmissions"/"dayzOffline.chernarusplus"),"target":str(self.game/"mpmissions"/"dayzOffline.chernarusplus")}]}
 def tearDown(self):self.temp.cleanup()
 def test_discovers_and_switches_only_available_missions(self):
  view=discover_missions(self.record);self.assertEqual(view["schema_version"],2);self.assertEqual(view["current"],"dayzOffline.chernarusplus")
  by_id={x["id"]:x for x in view["missions"]}
  self.assertEqual(set(by_id),{"dayzOffline.chernarusplus","dayzOffline.enoch","dayzOffline.sakhal"})
  self.assertTrue(by_id["dayzOffline.chernarusplus"]["active"])
  self.assertTrue(by_id["dayzOffline.chernarusplus"]["installed"])
  self.assertTrue(by_id["dayzOffline.enoch"]["available"])
  self.assertFalse(by_id["dayzOffline.enoch"]["installed"])
  self.assertFalse(by_id["dayzOffline.sakhal"]["available"])
  self.assertFalse(by_id["dayzOffline.sakhal"]["can_activate"])
  changed=apply_mission(self.record,"dayzOffline.enoch");self.assertEqual(current_mission(changed),"dayzOffline.enoch")
  self.assertEqual(changed["profile_context"]["dayz_mission"],"dayzOffline.enoch")
  self.assertTrue((self.state/"mpmissions"/"dayzOffline.enoch").is_dir())
  self.assertEqual(changed["bind_paths"],[{"source":str(self.state/"mpmissions"/"dayzOffline.enoch"),"target":str(self.game/"mpmissions"/"dayzOffline.enoch")}])
  self.assertTrue((self.state/"mpmissions"/"dayzOffline.chernarusplus"/"storage_1"/"players.db").is_file())
  with self.assertRaises(FileNotFoundError):apply_mission(self.record,"community.not-installed")
 def test_switch_updates_content_base_bind_paths_used_by_mod_activation(self):
  record={**self.record,
   "content_base_bind_paths":[{"source":str(self.state/"mpmissions"/"dayzOffline.chernarusplus"),"target":str(self.game/"mpmissions"/"dayzOffline.chernarusplus")}],
   "bind_paths":[
    {"source":str(self.state/"mpmissions"/"dayzOffline.chernarusplus"),"target":str(self.game/"mpmissions"/"dayzOffline.chernarusplus")},
    {"source":str(self.state/".dsm"/"dayz-keys"),"target":str(self.game/"keys")},
   ],
  }
  changed=apply_mission(record,"dayzOffline.enoch")
  expected={"source":str(self.state/"mpmissions"/"dayzOffline.enoch"),"target":str(self.game/"mpmissions"/"dayzOffline.enoch")}
  self.assertEqual(changed["content_base_bind_paths"],[expected])
  self.assertIn(expected,changed["bind_paths"])
  self.assertIn({"source":str(self.state/".dsm"/"dayz-keys"),"target":str(self.game/"keys")},changed["bind_paths"])
  self.assertFalse(any("chernarusplus" in b["source"] or "chernarusplus" in b["target"] for b in changed["content_base_bind_paths"]))
 def test_discovers_community_mission_and_marks_source(self):
  mission=self.game/"mpmissions"/"dayzOffline.namalsk";mission.mkdir(parents=True)
  view=discover_missions(self.record);item=next(x for x in view["missions"] if x["id"]=="dayzOffline.namalsk")
  self.assertTrue(item["community"]);self.assertFalse(item["official"])
  self.assertTrue(item["available"]);self.assertFalse(item["installed"]);self.assertTrue(item["can_activate"])
  changed=apply_mission(self.record,item["id"])
  self.assertEqual(current_mission(changed),"dayzOffline.namalsk")
  self.assertTrue((self.state/"mpmissions"/"dayzOffline.namalsk").is_dir())
 def test_mod_preflight_keeps_unknown_separate_from_compatible(self):
  snapshot={"entries":[
   {"content_id":"cf","game_id":"dayz","package_id":"221100:1559212036","activation":{"adapter":"dayz","mode":"mod"},"dependencies":[],"dayz_map_compatibility":{"all_missions":True}},
   {"content_id":"admin","game_id":"dayz","package_id":"221100:1828439124","activation":{"adapter":"dayz","mode":"mod"},"dependencies":[]},
  ]}
  result=mod_compatibility_preflight(snapshot,"dayzOffline.enoch")
  self.assertEqual(result["status"],"unknown");self.assertFalse(result["blocking"])
  self.assertEqual(result["active_mods"],2);self.assertEqual(result["compatible"],1);self.assertEqual(result["unknown"],1);self.assertEqual(result["incompatible"],0)
 def test_mod_preflight_blocks_explicit_incompatibility_and_missing_dependency(self):
  snapshot={"entries":[
   {"content_id":"map-specific","game_id":"dayz","package_id":"221100:1","activation":{"adapter":"dayz","mode":"mod"},"dependencies":[],"dayz_map_compatibility":{"compatible_missions":["dayzOffline.chernarusplus"]}},
   {"content_id":"dependent","game_id":"dayz","package_id":"221100:2","activation":{"adapter":"dayz","mode":"mod"},"dependencies":["missing-base"],"dayz_map_compatibility":{"all_missions":True}},
  ]}
  result=mod_compatibility_preflight(snapshot,"dayzOffline.enoch")
  self.assertEqual(result["status"],"incompatible");self.assertTrue(result["blocking"])
  self.assertEqual(result["incompatible"],2)
  reasons={item["reason"] for item in result["items"]};self.assertIn("mission_not_in_compatibility_allowlist",reasons);self.assertIn("missing_dependency",reasons)
 def test_wipe_backs_up_and_removes_current_persistence(self):
  result=wipe(self.record,"persistence",True);self.assertTrue(Path(result["backup"]).is_file())
  self.assertFalse((self.state/"mpmissions"/"dayzOffline.chernarusplus"/"storage_1").exists())
  self.assertTrue((self.state/"config"/"serverDZ.cfg").is_file())
 def test_wipe_honors_private_storage_argument(self):
  storage=self.state/"storage";storage.mkdir();(storage/"players.db").write_text("state",encoding="utf-8")
  record={**self.record,"arguments":[*self.record["arguments"],"-storage="+str(storage)]}
  result=wipe(record,"persistence",True)
  self.assertFalse(storage.exists())
  self.assertTrue(Path(result["backup"]).is_file())

if __name__=="__main__":unittest.main()
