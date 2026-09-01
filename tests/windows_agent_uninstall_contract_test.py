#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agents" / "windows" / "service" / "uninstall-agent.ps1"
BUILDER = ROOT / "release" / "build_windows_agent_package.py"


class WindowsAgentUninstallContractTest(unittest.TestCase):
    def test_uninstall_has_safe_preserve_and_purge_modes(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("[switch]$Purge", text)
        self.assertIn("Unregister-ScheduledTask", text)
        self.assertIn("Stop-ScheduledTask", text)
        self.assertIn("Get-CimInstance Win32_Process", text)
        self.assertIn("Capivara Agent.lnk", text)
        self.assertIn("Capivara Agent Tray.lnk", text)
        self.assertIn("@('instances', 'backups')", text)
        self.assertIn("Remove-Item $InstallRoot -Recurse -Force", text)
        self.assertIn("Assert-SafeRoot", text)
        self.assertIn("execute o PowerShell como Administrador", text)

    def test_windows_package_contains_uninstall_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                ["python3", str(BUILDER), "HEAD", tmp],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            version = (ROOT / "version").read_text(encoding="utf-8").strip()
            import zipfile

            archive = Path(tmp) / f"capivara-agent-windows-{version}.zip"
            with zipfile.ZipFile(archive) as package:
                names = set(package.namelist())
            expected = f"capivara-agent-windows-{version}/service/uninstall-agent.ps1"
            self.assertIn(expected, names)

    def test_danger_zone_explicitly_describes_controller_only_removal(self):
        html = (ROOT / "dashboard" / "web" / "agent-details.html").read_text(encoding="utf-8")
        self.assertIn(
            "Esta ação remove apenas o Agent e o Node do Controller e não toca nos arquivos da máquina remota.",
            html,
        )


if __name__ == "__main__":
    unittest.main()
