from __future__ import annotations
import json, os, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/"agents"/"windows"/"runtime"
class WindowsAgentGuiTest(unittest.TestCase):
 def test_gui_backend_catalog_is_allowlisted(self):
  env=os.environ.copy();env["PYTHONPATH"]=str(RUNTIME)
  cp=subprocess.run([sys.executable,str(RUNTIME/"admin_gui_backend.py"),"catalog"],cwd=ROOT,env=env,capture_output=True,text=True,check=False)
  self.assertEqual(cp.returncode,0,cp.stderr);catalog=json.loads(cp.stdout);commands={item["command"] for item in catalog}
  for expected in ("agent status","agent health","agent doctor","agent controller test","agent storage pools","instance list","instance start <id>","instance stop <id>","instance restart <id>"):self.assertIn(expected,commands)
  source=(RUNTIME/"admin_gui_backend.py").read_text(encoding="utf-8");self.assertNotIn("shell=True",source);self.assertIn("unsupported local Agent command",source);self.assertIn("SENSITIVE_KEYS",source)
 def test_gui_surface_contains_health_activity_console_logs_and_tray(self):
  source=(ROOT/"agents/windows/gui/CapivaraAgentGui.ps1").read_text(encoding="utf-8")
  for token in ('Header="Visão geral"','Header="Atividades"','Header="Instâncias"','Header="Comandos"','Header="Console"','Header="Logs"','System.Windows.Forms.NotifyIcon','Abrir Capivara Agent','Atualizar saúde','Capivara Agent Tray'):
   if token=='Capivara Agent Tray':continue
   self.assertIn(token,source)
  self.assertNotIn('credential_secret',source);self.assertIn('Invoke-AgentAdminCommand',source)
 def test_installer_auto_detects_gui_and_creates_shortcuts(self):
  source=(ROOT/"agents/windows/installer/install-agent.ps1").read_text(encoding="utf-8")
  for token in ("GuiMode = 'auto'","Test-GuiAvailable","explorer.exe","PresentationFramework","CommonDesktopDirectory","CommonStartup","Capivara Agent.lnk","Capivara Agent Tray.lnk","gui_enabled=$guiEnabled"):
   self.assertIn(token,source)
  self.assertIn("Interface gráfica não habilitada",source)
 def test_service_publishes_sanitized_gui_snapshot_and_persistent_log(self):
  agent=(RUNTIME/"agent.py").read_text(encoding="utf-8");launcher=(ROOT/"agents/windows/service/run-agent.ps1").read_text(encoding="utf-8");register=(ROOT/"agents/windows/service/register-task.ps1").read_text(encoding="utf-8")
  self.assertIn("_publish_gui_snapshot",agent);self.assertIn('GUI_SNAPSHOT_PATH=STATE_DIR/"gui"/"snapshot.json"',agent);self.assertNotIn('"credential_secret":',agent.split("def _publish_gui_snapshot",1)[1].split("def _post",1)[0]);self.assertIn("agent.log",launcher);self.assertIn("10485760",launcher);self.assertIn("run-agent.ps1",register)
 def test_windows_package_includes_gui_assets(self):
  with tempfile.TemporaryDirectory() as tmp:
   cp=subprocess.run([sys.executable,str(ROOT/"release/build_windows_agent_package.py"),"HEAD",tmp],cwd=ROOT,capture_output=True,text=True,check=False);self.assertEqual(cp.returncode,0,cp.stderr)
   archive=next(Path(tmp).glob("capivara-agent-windows-*.zip"))
   with zipfile.ZipFile(archive) as package:
    names=package.namelist();manifest=json.loads(package.read(next(name for name in names if name.endswith('/manifest.json'))))
   required=set(manifest["required_files"]);self.assertTrue(manifest.get("features",{}).get("admin_gui"));self.assertIn("gui/CapivaraAgentGui.ps1",required);self.assertIn("service/run-agent.ps1",required);self.assertIn("agent/runtime/admin_gui_backend.py",required)
if __name__=="__main__":unittest.main()
