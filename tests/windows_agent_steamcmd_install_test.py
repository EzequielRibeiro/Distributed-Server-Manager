#!/usr/bin/env python3
from __future__ import annotations
import importlib
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/"agents"/"windows"/"runtime"
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))

import capabilities
import game_data_executor

class WindowsSteamCmdInstallTest(unittest.TestCase):
 def test_install_steamcmd_is_system_action_without_game_selection(self):
  with tempfile.TemporaryDirectory() as td:
   def fake_download(_url,dst):
    with zipfile.ZipFile(dst,"w") as z:z.writestr("steamcmd.exe",b"fake")
   with mock.patch.dict(os.environ,{"PROGRAMDATA":td},clear=False),mock.patch.object(game_data_executor,"_download",side_effect=fake_download),mock.patch.object(game_data_executor,"_probe_steamcmd"):
    result=game_data_executor.execute({"action":"install-steamcmd","environment_id":"_system.steamcmd"})
    expected=Path(td)/"CapivaraAgent"/"tools"/"steamcmd"/"steamcmd.exe"
    self.assertTrue(expected.is_file())
    self.assertTrue(result["installed"])
    self.assertFalse(result["reused"])
    self.assertEqual(result["component"],"steamcmd")

 def test_managed_steamcmd_is_reported_as_capability(self):
  with tempfile.TemporaryDirectory() as td:
   executable=Path(td)/"CapivaraAgent"/"tools"/"steamcmd"/"steamcmd.exe"
   executable.parent.mkdir(parents=True)
   executable.write_bytes(b"fake")
   with mock.patch.dict(os.environ,{"PROGRAMDATA":td},clear=False),mock.patch.object(capabilities.shutil,"which",return_value=None):
    self.assertTrue(capabilities.detect_capabilities()["steamcmd"])

 def test_safe_member_rejects_windows_backslash_traversal(self):
  with self.assertRaises(RuntimeError):game_data_executor._safe_member(r"..\evil.exe")

if __name__=="__main__":unittest.main()
