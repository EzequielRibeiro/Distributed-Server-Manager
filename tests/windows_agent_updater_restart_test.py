#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
UPDATER_PATH=ROOT/"agents"/"windows"/"updater"/"updater.py"
spec=importlib.util.spec_from_file_location("windows_agent_updater",UPDATER_PATH)
updater=importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(updater)

class WindowsAgentUpdaterRestartTest(unittest.TestCase):
 def test_read_request_accepts_utf8_bom(self):
  with tempfile.TemporaryDirectory() as td:
   request=Path(td)/"update-request.json"
   request.write_text(json.dumps({"desired_version":"2.0.19"}),encoding="utf-8-sig")
   with mock.patch.object(updater,"REQUEST_PATH",request):
    self.assertEqual(updater._read_request()["desired_version"],"2.0.19")

 def test_stop_agent_task_reports_real_restart(self):
  completed=subprocess.CompletedProcess([],10,stdout="",stderr="")
  with mock.patch.object(updater.subprocess,"run",return_value=completed) as run,mock.patch.object(updater.time,"sleep") as sleep:
   self.assertTrue(updater._stop_agent_task())
   self.assertIn("Stop-ScheduledTask",run.call_args.args[0][3])
   sleep.assert_called_once_with(2)

 def test_reconcile_stops_old_runtime_then_confirms_running(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)/"CapivaraAgent"
   for relative in ("service/register-task.ps1","service/run-agent.ps1","runtime/agent.py"):
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("test",encoding="utf-8")
   ok=subprocess.CompletedProcess([],0,stdout="",stderr="")
   with mock.patch.object(updater,"INSTALL_ROOT",root),mock.patch.object(updater,"DATA_ROOT",Path(td)/"data"),mock.patch.object(updater,"_stop_agent_task",return_value=True) as stop,mock.patch.object(updater,"_powershell",return_value=ok) as powershell,mock.patch.object(updater,"_task_is_running",side_effect=[False,True]),mock.patch.object(updater.time,"sleep"):
    result=updater._reconcile_runtime_integration()
   stop.assert_called_once_with()
   powershell.assert_called_once()
   self.assertTrue(result["task_reconciled"])
   self.assertTrue(result["task_restarted"])
   self.assertTrue(result["task_running"])

if __name__=="__main__":unittest.main()
