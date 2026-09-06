#!/usr/bin/env python3
from __future__ import annotations
import os,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/"agents"/"windows"/"runtime"
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
from runtime_materialization import _prepare_private_state,_validate_materialization
from runtime_spec import validate_runtime_spec
from profiles.registry import resolve_profile

@unittest.skipUnless(os.name=="nt","Windows materialization contract")
class WindowsRuntimeSeedScopeTest(unittest.TestCase):
 def test_provider_seed_can_materialize_private_ark_tree(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);provider=root/"provider";state=root/"state";exe_rel=Path("ShooterGame/Binaries/Win64/ArkAscendedServer.exe")
   (provider/exe_rel).parent.mkdir(parents=True);(provider/exe_rel).write_bytes(b"ark");(provider/"ShooterGame/Saved/Config/WindowsServer").mkdir(parents=True);(provider/"ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini").write_text("seed",encoding="utf-8")
   instance={"instance_id":"ark-a","agent_id":"agent-test","game_id":"arksurvivalascended","environment_id":"arksurvivalascended.stable"}
   context={"install_path":str(provider),"instance_state_root":str(state),"ports":{"game":{"port":7777,"protocol":"udp"},"query":{"port":27015,"protocol":"udp"}},"catalog_runtime_policy":{"runtime_id":"arksurvivalascended.stable","executable":"ShooterGame/Binaries/Win64/ArkAscendedServer.exe","arguments":[]}}
   spec=validate_runtime_spec(resolve_profile(instance).build_runtime_spec(instance,context),expected_agent_id="agent-test")
   self.assertFalse(Path(spec["working_directory"]).exists());_prepare_private_state(spec)
   self.assertTrue(Path(spec["executable"]).is_file());self.assertEqual("seed",(Path(spec["configuration_root"])/"GameUserSettings.ini").read_text(encoding="utf-8"));self.assertTrue(_validate_materialization(spec)["matches"])
 def test_provider_content_executable_can_run_with_private_working_directory(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);provider=root/"provider";state=root/"state";provider.mkdir();state.mkdir();exe=provider/"RustDedicated.exe";exe.write_bytes(b"rust");working=state/"runtime";working.mkdir()
   spec=validate_runtime_spec({"instance_id":"rust-a","agent_id":"agent-test","runtime_id":"rust-a","adapter":"windows-process","working_directory":str(working),"executable":str(exe),"executable_scope":"provider-content","seed_source_root":str(provider),"arguments":[],"environment":{},"desired_state":"stopped","instance_state_root":str(state)})
   self.assertTrue(_validate_materialization(spec)["matches"])

if __name__=="__main__":unittest.main()
