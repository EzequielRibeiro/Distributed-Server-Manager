#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/"agents"/"linux"/"runtime"
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
from profiles.registry import resolve_profile
from runtime_spec import validate_runtime_spec

class SourceRuntimeInstanceIsolationTest(unittest.TestCase):
 def ports(self,base:int=27015)->dict:return {"game_udp":{"port":base,"protocol":"udp"},"game_tcp":{"port":base,"protocol":"tcp"}}
 def build(self,game_id:str,instance_id:str,base:int=27015)->dict:
  environment_id=f"{game_id}.stable";args_by_game={"garrysmod":["-game","garrysmod","-console","+map","gm_construct"],"left4dead2":["-game","left4dead2","-console","+map","c1m1_hotel"],"teamfortress2":["-game","tf","+map","cp_dustbowl"]}
  instance={"instance_id":instance_id,"agent_id":"agent-test","game_id":game_id,"environment_id":environment_id,"desired_state":"stopped"}
  context={"install_path":f"/srv/capivara/game-data/{game_id}/serverfiles","instance_state_root":f"/srv/capivara/instances/{instance_id}","ports":self.ports(base),"arguments":args_by_game[game_id],"catalog_runtime_policy":{"runtime_id":environment_id,"executable":"srcds_run","working_directory":"."}}
  return validate_runtime_spec(resolve_profile(instance).build_runtime_spec(instance,context),expected_agent_id="agent-test")
 def test_registry_routes_source_games(self):
  for game_id in ("garrysmod","left4dead2","teamfortress2"):
   self.assertEqual("SourceRuntimeProfile",resolve_profile({"game_id":game_id,"environment_id":f"{game_id}.stable"}).__class__.__name__)
 def test_garrysmod_cfg_data_and_logs_are_instance_private(self):
  spec=self.build("garrysmod","gmod-a");install=Path("/srv/capivara/game-data/garrysmod/serverfiles");private=Path("/srv/capivara/instances/gmod-a/garrysmod")
  self.assertEqual([{"source":str(install/"garrysmod/cfg"),"target":str(private/"cfg")}],spec["seed_directories"])
  self.assertEqual({str(private/"cfg"),str(private/"data"),str(private/"logs")},{x["source"] for x in spec["bind_paths"]})
 def test_left4dead2_cfg_and_logs_are_instance_private(self):
  spec=self.build("left4dead2","l4d2-a");private=Path("/srv/capivara/instances/l4d2-a/left4dead2")
  self.assertEqual({str(private/"cfg"),str(private/"logs")},{x["source"] for x in spec["bind_paths"]})
 def test_teamfortress2_cfg_and_logs_are_instance_private(self):
  spec=self.build("teamfortress2","tf2-a");install=Path("/srv/capivara/game-data/teamfortress2/serverfiles");private=Path("/srv/capivara/instances/tf2-a/tf")
  self.assertEqual("source",spec["profile"]);self.assertEqual(["-port","27015"],spec["arguments"][:2])
  self.assertEqual([{"source":str(install/"tf/cfg"),"target":str(private/"cfg")}],spec["seed_directories"])
  self.assertEqual({str(private/"cfg"),str(private/"logs")},{x["source"] for x in spec["bind_paths"]})
 def test_two_source_instances_share_binary_but_never_mutable_paths(self):
  for game_id in ("garrysmod","left4dead2","teamfortress2"):
   first=self.build(game_id,f"{game_id}-a",27015);second=self.build(game_id,f"{game_id}-b",27115)
   self.assertEqual(first["executable"],second["executable"]);self.assertEqual(first["working_directory"],second["working_directory"])
   self.assertNotEqual(first["seed_directories"][0]["target"],second["seed_directories"][0]["target"])
   self.assertTrue({x["source"] for x in first["bind_paths"]}.isdisjoint({x["source"] for x in second["bind_paths"]}))
if __name__=="__main__":unittest.main()
