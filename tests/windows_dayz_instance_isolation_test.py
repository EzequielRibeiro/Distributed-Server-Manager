#!/usr/bin/env python3
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/"agents"/"windows"/"runtime"
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))

from profiles.dayz import DayZRuntimeProfile,ProfileError
from runtime_spec import validate_runtime_spec
from runtime_materialization import _prepare_private_state


class WindowsDayZInstanceIsolationTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.shared=self.root/"game-data"/"dayz"/"serverfiles";self.shared.mkdir(parents=True)
  (self.shared/"DayZServer_x64.exe").write_bytes(b"fake")
  (self.shared/"serverDZ.cfg").write_text('hostname="Capivara";\n',encoding="utf-8")
  mission=self.shared/"mpmissions"/"dayzOffline.chernarusplus";db=mission/"db";db.mkdir(parents=True);(db/"messages.xml").write_text("<messages/>\n",encoding="utf-8");(db/"types.xml").write_text("<types/>\n",encoding="utf-8")
 def tearDown(self):self.tmp.cleanup()
 def _spec(self,instance_id,port):
  state=self.root/"instances"/instance_id
  raw=DayZRuntimeProfile().build_runtime_spec({"instance_id":instance_id,"agent_id":"agent-win","game_id":"dayz"},{"install_path":str(self.shared),"working_directory":str(self.shared),"instance_state_root":str(state),"ports":{"game":{"port":port,"protocol":"udp"},"game_aux":{"port":port+2,"protocol":"udp"},"steam_query":{"port":port+100,"protocol":"udp"}}})
  return validate_runtime_spec(raw,expected_agent_id="agent-win")
 def test_two_instances_share_binaries_but_not_mutable_state(self):
  a=self._spec("dayz-a",2302);b=self._spec("dayz-b",2402)
  self.assertEqual(a["executable"],b["executable"])
  self.assertEqual(a["working_directory"],b["working_directory"])
  self.assertNotEqual(a["instance_state_root"],b["instance_state_root"])
  self.assertNotEqual(a["config_path"],b["config_path"])
  self.assertIn(f'-mission={Path(a["instance_state_root"])/"mpmissions"/"dayzOffline.chernarusplus"}',a["arguments"])
  self.assertIn(f'-storage={Path(a["instance_state_root"])/"storage"}',a["arguments"])
  self.assertIn(f'-profiles={Path(a["instance_state_root"])/"profiles"}',a["arguments"])
  _prepare_private_state(a);_prepare_private_state(b)
  a_msg=Path(a["instance_state_root"])/"mpmissions"/"dayzOffline.chernarusplus"/"db"/"messages.xml";b_msg=Path(b["instance_state_root"])/"mpmissions"/"dayzOffline.chernarusplus"/"db"/"messages.xml"
  self.assertTrue(a_msg.is_file());self.assertTrue(b_msg.is_file());a_msg.write_text("<messages><a/></messages>\n",encoding="utf-8")
  self.assertEqual(b_msg.read_text(encoding="utf-8"),"<messages/>\n");self.assertEqual((self.shared/"mpmissions"/"dayzOffline.chernarusplus"/"db"/"messages.xml").read_text(encoding="utf-8"),"<messages/>\n")
  _prepare_private_state(a);self.assertIn("<a/>",a_msg.read_text(encoding="utf-8"))
 def test_customer_arguments_cannot_override_private_paths(self):
  with self.assertRaises(ProfileError):
   DayZRuntimeProfile().build_runtime_spec({"instance_id":"dayz-a","agent_id":"agent-win","game_id":"dayz"},{"install_path":str(self.shared),"instance_state_root":str(self.root/"instances"/"dayz-a"),"ports":{"game":{"port":2302,"protocol":"udp"},"game_aux":{"port":2304,"protocol":"udp"},"steam_query":{"port":2402,"protocol":"udp"}},"arguments":["-storage=C:\\shared"]})
 def test_relative_private_seed_path_is_rejected(self):
  spec=self._spec("dayz-a",2302);spec["seed_directories"]=[{"source":"relative","target":str(Path(spec["instance_state_root"])/"mission")}]
  with self.assertRaises(Exception):validate_runtime_spec(spec,expected_agent_id="agent-win")


if __name__=="__main__":unittest.main()
