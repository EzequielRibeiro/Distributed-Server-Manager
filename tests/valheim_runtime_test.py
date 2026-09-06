#!/usr/bin/env python3
from __future__ import annotations
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/"agents/linux/runtime"
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
from profiles.registry import resolve_profile
from runtime_spec import validate_runtime_spec
from materializers.systemd import render_unit
import valheim_launch

class ValheimRuntimeTest(unittest.TestCase):
 def build(self,iid:str,port:int)->dict:
  instance={"instance_id":iid,"agent_id":"agent-test","game_id":"valheim","environment_id":"valheim.stable"}
  context={"install_path":"/srv/capivara/game-data/valheim/serverfiles","instance_state_root":f"/srv/capivara/instances/{iid}","ports":{"game":{"port":port,"protocol":"udp"},"game_aux":{"port":port+1,"protocol":"udp"}},"catalog_runtime_policy":{"runtime_id":"valheim.stable","executable":"valheim_server.x86_64","arguments":[]}}
  return validate_runtime_spec(resolve_profile(instance).build_runtime_spec(instance,context),expected_agent_id="agent-test")
 def test_two_instances_share_binary_but_not_savedir(self):
  a=self.build("val-a",2456);b=self.build("val-b",2556)
  self.assertEqual(a["working_directory"],b["working_directory"])
  self.assertNotEqual(a["configuration_root"],b["configuration_root"])
  self.assertIn(a["configuration_root"],a["arguments"]);self.assertIn(b["configuration_root"],b["arguments"])
  self.assertEqual(a["secret_refs"],[{"name":"VALHEIM_PASSWORD","ref":"instance/val-a/VALHEIM_PASSWORD","target":"file"}])
  self.assertNotIn("-password",a["arguments"])
 def test_aux_port_must_be_next_udp_port(self):
  instance={"instance_id":"bad","agent_id":"agent-test","game_id":"valheim","environment_id":"valheim.stable"}
  context={"install_path":"/srv/game","instance_state_root":"/srv/state/bad","ports":{"game":{"port":2456,"protocol":"udp"},"game_aux":{"port":2459,"protocol":"udp"}},"catalog_runtime_policy":{"runtime_id":"valheim.stable","executable":"valheim_server.x86_64","arguments":[]}}
  with self.assertRaisesRegex(Exception,"game_aux"):
   resolve_profile(instance).build_runtime_spec(instance,context)
 def test_unit_contains_credential_reference_but_no_game_password_token(self):
  spec=self.build("val-a",2456)
  with patch("materializers.systemd.credential_path",return_value="/run/capivara-secrets/val-a-password"):
   unit=render_unit(spec)
  self.assertIn("LoadCredential=VALHEIM_PASSWORD:/run/capivara-secrets/val-a-password",unit)
  self.assertIn("valheim_launch.py",unit);self.assertIn('"--password-credential"',unit);self.assertNotIn('"-password"',unit)
 def test_launcher_reads_credential_only_at_exec(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);server=root/"valheim_server.x86_64";server.write_bytes(b"stub");cred=root/"VALHEIM_PASSWORD";cred.write_text("supersecret",encoding="utf-8")
   argv=["--server",str(server),"--password-credential","VALHEIM_PASSWORD","--","-name","Test","-port","2456"]
   with patch.dict(os.environ,{"CREDENTIALS_DIRECTORY":td},clear=False),patch.object(valheim_launch.os,"execv") as execv:
    self.assertEqual(valheim_launch.main(argv),0)
   called=execv.call_args.args[1];self.assertEqual(called[-2:], ["-password","supersecret"])

if __name__=="__main__":unittest.main()
