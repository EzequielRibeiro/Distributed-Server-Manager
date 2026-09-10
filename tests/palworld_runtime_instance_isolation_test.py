#!/usr/bin/env python3
from __future__ import annotations
import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/"agents"/"linux"/"runtime"
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
from profiles.base import ProfileError
from profiles.registry import resolve_profile
from runtime_spec import validate_runtime_spec
class PalworldRuntimeIsolationTest(unittest.TestCase):
 def build(self,instance_id:str,port:int)->dict:
  instance={"instance_id":instance_id,"agent_id":"agent-test","game_id":"palworld","environment_id":"palworld.stable"}
  context={"install_path":"/srv/capivara/game-data/palworld/serverfiles","instance_state_root":f"/srv/capivara/instances/{instance_id}","ports":{"game":{"port":port,"protocol":"udp"},"rcon":{"port":port+1,"protocol":"tcp"},"rest_api":{"port":port+2,"protocol":"tcp"}},"catalog_runtime_policy":{"runtime_id":"palworld.stable","executable":"PalServer.sh","working_directory":"."}}
  return validate_runtime_spec(resolve_profile(instance).build_runtime_spec(instance,context),expected_agent_id="agent-test")
 def test_registry(self):self.assertEqual("PalworldRuntimeProfile",resolve_profile({"game_id":"palworld","environment_id":"palworld.stable"}).__class__.__name__)
 def test_saved_state_is_private(self):
  spec=self.build("pal-a",8211);shared=Path("/srv/capivara/game-data/palworld/serverfiles/Pal/Saved");private=Path("/srv/capivara/instances/pal-a/Pal/Saved")
  self.assertEqual([{"source":str(shared),"target":str(private),"optional":True}],spec["seed_directories"]);self.assertEqual([{"source":str(private),"target":str(shared)}],spec["bind_paths"]);self.assertEqual("-port=8211",spec["arguments"][0])
 def test_two_instances_do_not_share_saved_state(self):
  a=self.build("pal-a",8211);b=self.build("pal-b",8311);self.assertEqual(a["executable"],b["executable"]);self.assertNotEqual(a["bind_paths"][0]["source"],b["bind_paths"][0]["source"]);self.assertEqual(a["bind_paths"][0]["target"],b["bind_paths"][0]["target"])
 def test_admin_ports_are_preserved_with_expected_protocols(self):
  spec=self.build("pal-a",8211)
  self.assertEqual({"port":8211,"protocol":"udp"},spec["ports"]["game"])
  self.assertEqual({"port":8212,"protocol":"tcp"},spec["ports"]["rcon"])
  self.assertEqual({"port":8213,"protocol":"tcp"},spec["ports"]["rest_api"])
 def test_rejects_non_tcp_admin_ports(self):
  instance={"instance_id":"pal-a","agent_id":"agent-test","game_id":"palworld","environment_id":"palworld.stable"}
  base={"install_path":"/srv/capivara/game-data/palworld/serverfiles","instance_state_root":"/srv/capivara/instances/pal-a","catalog_runtime_policy":{"runtime_id":"palworld.stable","executable":"PalServer.sh"}}
  with self.assertRaisesRegex(ProfileError,"RCON reservation must use TCP"):
   resolve_profile(instance).build_runtime_spec(instance,{**base,"ports":{"game":{"port":8211,"protocol":"udp"},"rcon":{"port":8212,"protocol":"udp"}}})
  with self.assertRaisesRegex(ProfileError,"REST API reservation must use TCP"):
   resolve_profile(instance).build_runtime_spec(instance,{**base,"ports":{"game":{"port":8211,"protocol":"udp"},"rest_api":{"port":8213,"protocol":"udp"}}})
 def test_catalog_reserves_palworld_game_rcon_and_rest_ports(self):
  runtime=json.loads((ROOT/"catalog"/"v2"/"games"/"palworld"/"runtimes"/"stable.json").read_text(encoding="utf-8"))
  ports=runtime["network"]["ports"]
  self.assertEqual([
   {"name":"game","protocol":"udp","offset":0},
   {"name":"rcon","protocol":"tcp","offset":1},
   {"name":"rest_api","protocol":"tcp","offset":2},
  ],ports)
  self.assertEqual([{"kind":"argument","template":"-port={game}"}],runtime["network"]["apply"])
if __name__=="__main__":unittest.main()
