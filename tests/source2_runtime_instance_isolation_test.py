#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/"agents"/"linux"/"runtime"
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
from profiles.registry import resolve_profile
from runtime_spec import validate_runtime_spec

class Source2RuntimeInstanceIsolationTest(unittest.TestCase):
 def build(self,instance_id:str,port:int)->dict:
  instance={"instance_id":instance_id,"agent_id":"agent-test","game_id":"counterstrike2","environment_id":"counterstrike2.stable","desired_state":"stopped"}
  context={"install_path":"/srv/capivara/game-data/counterstrike2/serverfiles","instance_state_root":f"/srv/capivara/instances/{instance_id}","ports":{"game":{"port":port,"protocol":"udp"}},"arguments":["-dedicated","+map","de_dust2"],"catalog_runtime_policy":{"runtime_id":"counterstrike2.stable","executable":"game/bin/linuxsteamrt64/cs2","working_directory":"."}}
  return validate_runtime_spec(resolve_profile(instance).build_runtime_spec(instance,context),expected_agent_id="agent-test")
 def test_registry_uses_source2_profile(self):
  profile=resolve_profile({"game_id":"counterstrike2","environment_id":"counterstrike2.stable"});self.assertEqual("Source2RuntimeProfile",profile.__class__.__name__)
 def test_cfg_and_logs_are_private(self):
  spec=self.build("cs2-a",27015);install=Path("/srv/capivara/game-data/counterstrike2/serverfiles/game/csgo");private=Path("/srv/capivara/instances/cs2-a/game/csgo")
  self.assertEqual("source2",spec["profile"]);self.assertEqual(["-port","27015"],spec["arguments"][:2])
  self.assertEqual([{"source":str(install/"cfg"),"target":str(private/"cfg")}],spec["seed_directories"])
  self.assertEqual({str(private/"cfg"),str(private/"logs")},{x["source"] for x in spec["bind_paths"]})
 def test_two_instances_share_binary_but_not_mutable_state(self):
  a=self.build("cs2-a",27015);b=self.build("cs2-b",27115)
  self.assertEqual(a["executable"],b["executable"]);self.assertEqual(a["working_directory"],b["working_directory"])
  self.assertNotEqual(a["seed_directories"][0]["target"],b["seed_directories"][0]["target"])
  self.assertTrue({x["source"] for x in a["bind_paths"]}.isdisjoint({x["source"] for x in b["bind_paths"]}))
if __name__=="__main__":unittest.main()
