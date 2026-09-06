#!/usr/bin/env python3
from __future__ import annotations
import importlib,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def registry(platform:str):
 runtime=ROOT/"agents"/platform/"runtime"
 for name in list(sys.modules):
  if name=="profiles" or name.startswith("profiles."):del sys.modules[name]
 sys.path.insert(0,str(runtime))
 try:return importlib.import_module("profiles.registry")
 finally:sys.path.remove(str(runtime))

def context(install:Path,state:Path)->dict:
 return {"install_path":str(install),"content_root":str(install),"instance_state_root":str(state),"ports":{"game":{"port":2302,"protocol":"udp"},"steam_query":{"port":2303,"protocol":"udp"},"steam_master":{"port":2304,"protocol":"udp"},"von_reserved":{"port":2305,"protocol":"udp"},"battleye":{"port":2306,"protocol":"udp"}},"catalog_runtime_policy":{"runtime_id":"arma3.stable","executable":"arma3server","working_directory":"."},"arguments":[]}
class Arma3RuntimeIsolationTest(unittest.TestCase):
 def test_profiles_registered_on_linux_and_windows(self):
  for platform in ("linux","windows"):self.assertIn("arma3.stable",set(registry(platform).supported_profiles()))
 def test_platform_executable_and_private_profiles(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();install=root/"shared"/"arma3";install.mkdir(parents=True)
   for platform,expected in (("linux","arma3server_x64"),("windows","arma3server_x64.exe")):
    reg=registry(platform);profile=reg.resolve_profile({"game_id":"arma3","environment_id":"arma3.stable"});state=root/platform/"arma-a";ctx=context(install,state)
    spec=profile.build_runtime_spec({"instance_id":"arma-a","agent_id":"agent-1","game_id":"arma3","environment_id":"arma3.stable"},ctx)
    self.assertEqual(Path(spec["executable"]).name,expected);self.assertIn("-port=2302",spec["arguments"]);self.assertIn(f"-profiles={state/'profiles'}",spec["arguments"]);self.assertEqual(set(spec["ports"]),{"game","steam_query","steam_master","von_reserved","battleye"});self.assertEqual(spec["configuration_root"],str(state/"profiles"))
 def test_two_instances_do_not_share_profiles(self):
  for platform in ("linux","windows"):
   reg=registry(platform);profile=reg.resolve_profile({"game_id":"arma3","environment_id":"arma3.stable"})
   with tempfile.TemporaryDirectory() as td:
    root=Path(td).resolve();install=root/"shared";install.mkdir();a=root/"a";b=root/"b"
    sa=profile.build_runtime_spec({"instance_id":"a","agent_id":"agent-1","game_id":"arma3","environment_id":"arma3.stable"},context(install,a));sb=profile.build_runtime_spec({"instance_id":"b","agent_id":"agent-1","game_id":"arma3","environment_id":"arma3.stable"},context(install,b))
    self.assertNotEqual(sa["configuration_root"],sb["configuration_root"]);self.assertEqual(sa["working_directory"],sb["working_directory"])
if __name__=="__main__":unittest.main()
