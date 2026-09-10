#!/usr/bin/env python3
from __future__ import annotations
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/"agents"/"linux"/"runtime"
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
from catalog_runtime_policy import apply_policy,materialize_network_properties
from profiles.base import ProfileError
from profiles.registry import resolve_profile
from runtime_spec import validate_runtime_spec
class PalworldRuntimeIsolationTest(unittest.TestCase):
 def build(self,instance_id:str,port:int)->dict:
  instance={"instance_id":instance_id,"agent_id":"agent-test","game_id":"palworld","environment_id":"palworld.stable"}
  context={"install_path":"/srv/capivara/game-data/palworld/serverfiles","instance_state_root":f"/srv/capivara/instances/{instance_id}","ports":{"game":{"port":port,"protocol":"udp"},"rcon":{"port":port+1,"protocol":"tcp"},"rest_api":{"port":port+2,"protocol":"tcp"}},"catalog_runtime_policy":{"runtime_id":"palworld.stable","executable":"PalServer.sh","working_directory":"."}}
  raw=resolve_profile(instance).build_runtime_spec(instance,context)
  return validate_runtime_spec(apply_policy(raw,instance,context),expected_agent_id="agent-test")
 def test_registry(self):self.assertEqual("PalworldRuntimeProfile",resolve_profile({"game_id":"palworld","environment_id":"palworld.stable"}).__class__.__name__)
 def test_saved_state_is_private(self):
  spec=self.build("pal-a",8211);shared=Path("/srv/capivara/game-data/palworld/serverfiles/Pal/Saved");private=Path("/srv/capivara/instances/pal-a/Pal/Saved")
  self.assertEqual([{"source":str(shared),"target":str(private),"optional":True}],spec["seed_directories"]);self.assertEqual([{"source":str(private),"target":str(shared)}],spec["bind_paths"]);self.assertEqual("-port=8211",spec["arguments"][0]);self.assertEqual(4,spec["profile_version"])
 def test_two_instances_do_not_share_saved_state(self):
  a=self.build("pal-a",8211);b=self.build("pal-b",8311);self.assertEqual(a["executable"],b["executable"]);self.assertNotEqual(a["bind_paths"][0]["source"],b["bind_paths"][0]["source"]);self.assertEqual(a["bind_paths"][0]["target"],b["bind_paths"][0]["target"])
 def test_admin_ports_are_preserved_with_expected_protocols(self):
  spec=self.build("pal-a",8211)
  self.assertEqual({"port":8211,"protocol":"udp"},spec["ports"]["game"])
  self.assertEqual({"port":8212,"protocol":"tcp"},spec["ports"]["rcon"])
  self.assertEqual({"port":8213,"protocol":"tcp"},spec["ports"]["rest_api"])
  props=spec["catalog_network_properties"]
  self.assertEqual(["RCONPort","RESTAPIPort"],[p["key"] for p in props])
  self.assertEqual(["{{PORT_RCON}}","{{PORT_REST_API}}"],[p["value"] for p in props])
 def test_requires_tcp_admin_ports(self):
  instance={"instance_id":"pal-a","agent_id":"agent-test","game_id":"palworld","environment_id":"palworld.stable"}
  base={"install_path":"/srv/capivara/game-data/palworld/serverfiles","instance_state_root":"/srv/capivara/instances/pal-a","catalog_runtime_policy":{"runtime_id":"palworld.stable","executable":"PalServer.sh"}}
  with self.assertRaisesRegex(ProfileError,"requires a TCP RCON reservation"):
   resolve_profile(instance).build_runtime_spec(instance,{**base,"ports":{"game":{"port":8211,"protocol":"udp"},"rest_api":{"port":8213,"protocol":"tcp"}}})
  with self.assertRaisesRegex(ProfileError,"requires a TCP REST API reservation"):
   resolve_profile(instance).build_runtime_spec(instance,{**base,"ports":{"game":{"port":8211,"protocol":"udp"},"rcon":{"port":8212,"protocol":"tcp"}}})
  with self.assertRaisesRegex(ProfileError,"RCON reservation"):
   resolve_profile(instance).build_runtime_spec(instance,{**base,"ports":{"game":{"port":8211,"protocol":"udp"},"rcon":{"port":8212,"protocol":"udp"},"rest_api":{"port":8213,"protocol":"tcp"}}})
 def test_catalog_reserves_palworld_game_rcon_and_rest_ports(self):
  runtime=json.loads((ROOT/"catalog"/"v2"/"games"/"palworld"/"runtimes"/"stable.json").read_text(encoding="utf-8"))
  self.assertEqual([
   {"name":"game","protocol":"udp","offset":0,"exposure":"public"},
   {"name":"rcon","protocol":"tcp","offset":1,"exposure":"none"},
   {"name":"rest_api","protocol":"tcp","offset":2,"exposure":"none"},
  ],runtime["network"]["ports"])
  self.assertEqual([{"kind":"argument","template":"-port={game}"}],runtime["network"]["apply"])
 def test_materializes_admin_ports_inside_unreal_option_settings(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);config=root/"private"/"Config"/"LinuxServer";config.mkdir(parents=True)
   default=root/"DefaultPalWorldSettings.ini"
   default.write_text('[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(ServerName="A (test)",CrossplayPlatforms=(Steam,Xbox),RCONEnabled=False,RCONPort=25575,RESTAPIEnabled=False,RESTAPIPort=8212)\n',encoding="utf-8")
   spec={"working_directory":str(root),"configuration_root":str(config),"catalog_variables":{"PORT_RCON":"24011","PORT_REST_API":"24012"},"catalog_network_properties":[
    {"path":"PalWorldSettings.ini","key":"RCONPort","value":"{{PORT_RCON}}","syntax":"ue_option_settings","seed_from":"DefaultPalWorldSettings.ini"},
    {"path":"PalWorldSettings.ini","key":"RESTAPIPort","value":"{{PORT_REST_API}}","syntax":"ue_option_settings","seed_from":"DefaultPalWorldSettings.ini"},
   ]}
   written=materialize_network_properties(spec);text=(config/"PalWorldSettings.ini").read_text(encoding="utf-8")
   self.assertEqual(["PalWorldSettings.ini","PalWorldSettings.ini"],written)
   self.assertIn("RCONPort=24011",text);self.assertIn("RESTAPIPort=24012",text)
   self.assertIn("RCONEnabled=False",text);self.assertIn("RESTAPIEnabled=False",text)
   self.assertIn("CrossplayPlatforms=(Steam,Xbox)",text);self.assertIn('ServerName="A (test)"',text)
 def test_existing_private_settings_are_not_reseeded(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);config=root/"private";config.mkdir();target=config/"PalWorldSettings.ini";target.write_text("OptionSettings=(RCONEnabled=False,RCONPort=1,RESTAPIEnabled=False,RESTAPIPort=2,ServerName=Custom)\n",encoding="utf-8")
   (root/"DefaultPalWorldSettings.ini").write_text("OptionSettings=(ServerName=Default,RCONPort=9,RESTAPIPort=9)\n",encoding="utf-8")
   spec={"working_directory":str(root),"configuration_root":str(config),"catalog_variables":{"PORT_RCON":"3","PORT_REST_API":"4"},"catalog_network_properties":[{"path":"PalWorldSettings.ini","key":"RCONPort","value":"{{PORT_RCON}}","syntax":"ue_option_settings","seed_from":"DefaultPalWorldSettings.ini"},{"path":"PalWorldSettings.ini","key":"RESTAPIPort","value":"{{PORT_REST_API}}","syntax":"ue_option_settings","seed_from":"DefaultPalWorldSettings.ini"}]}
   materialize_network_properties(spec);text=target.read_text(encoding="utf-8")
   self.assertIn("ServerName=Custom",text);self.assertNotIn("ServerName=Default",text);self.assertIn("RCONPort=3",text);self.assertIn("RESTAPIPort=4",text)
if __name__=="__main__":unittest.main()