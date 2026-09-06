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
def ctx(install:Path,state:Path)->dict:
 return {"install_path":str(install),"content_root":str(install),"instance_state_root":str(state),"ports":{"game":{"port":28015,"protocol":"udp"},"rcon":{"port":28016,"protocol":"tcp"},"query":{"port":28017,"protocol":"udp"}},"catalog_runtime_policy":{"runtime_id":"rust.stable","executable":"RustDedicated","working_directory":".","arguments":["+server.port {{PORT_GAME}}"]},"arguments":[]}
class RustRuntimeIsolationTest(unittest.TestCase):
 def test_registered_on_linux_and_windows(self):
  for platform in ("linux","windows"):self.assertIn("rust.stable",set(registry(platform).supported_profiles()))
 def test_identity_ports_and_logs_are_private(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();install=root/"shared";install.mkdir()
   for platform,exe in (("linux","RustDedicated"),("windows","RustDedicated.exe")):
    reg=registry(platform);profile=reg.resolve_profile({"game_id":"rust","environment_id":"rust.stable"});state=root/platform/"rust-a";context=ctx(install,state)
    spec=profile.build_runtime_spec({"instance_id":"rust-a","agent_id":"agent-1","game_id":"rust","environment_id":"rust.stable"},context)
    self.assertEqual(Path(spec["executable"]).name,exe);self.assertEqual(spec["working_directory"],str(state/"runtime"));self.assertEqual(spec["configuration_root"],str(state/"runtime"/"server"/"rust-a"/"cfg"));self.assertEqual(context["catalog_runtime_policy"]["arguments"],[])
    joined=" ".join(spec["arguments"]);self.assertIn("+server.identity rust-a",joined);self.assertIn("+server.port 28015",joined);self.assertIn("+rcon.port 28016",joined);self.assertIn("+server.queryport 28017",joined);self.assertIn(str(state/"logs"/"rust.log"),spec["arguments"])
 def test_two_instances_do_not_share_runtime_identity(self):
  for platform in ("linux","windows"):
   reg=registry(platform);profile=reg.resolve_profile({"game_id":"rust","environment_id":"rust.stable"})
   with tempfile.TemporaryDirectory() as td:
    root=Path(td).resolve();install=root/"shared";install.mkdir();a=root/"a";b=root/"b"
    sa=profile.build_runtime_spec({"instance_id":"a","agent_id":"agent-1","game_id":"rust","environment_id":"rust.stable"},ctx(install,a));sb=profile.build_runtime_spec({"instance_id":"b","agent_id":"agent-1","game_id":"rust","environment_id":"rust.stable"},ctx(install,b))
    self.assertEqual(sa["executable"],sb["executable"]);self.assertNotEqual(sa["working_directory"],sb["working_directory"]);self.assertNotEqual(sa["configuration_root"],sb["configuration_root"])
if __name__=="__main__":unittest.main()
