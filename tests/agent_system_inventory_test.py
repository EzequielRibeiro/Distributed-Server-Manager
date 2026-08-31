#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "agents" / "windows" / "runtime"
LINUX = ROOT / "agents" / "linux" / "runtime"


class AgentSystemInventoryTest(unittest.TestCase):
    def test_windows_inventory_normalizes_cim_payload(self):
        sys.path.insert(0, str(WIN))
        try:
            import system_inventory as win_system
            payload = {
                "name": "Microsoft Windows 11 Pro",
                "version": "10.0.26100",
                "build": "26100",
                "architecture": "64-bit",
                "display_version": "24H2",
                "edition": "Professional",
            }
            with patch.object(win_system, "_run_powershell_json", return_value=payload):
                item = win_system.collect_system_inventory()
            self.assertEqual(item["family"], "windows")
            self.assertEqual(item["pretty_name"], "Microsoft Windows 11 Pro")
            self.assertEqual(item["display_version"], "24H2")
            self.assertEqual(item["build"], "26100")
            self.assertEqual(item["architecture"], "64-bit")
        finally:
            sys.path.remove(str(WIN))
            sys.modules.pop("system_inventory", None)

    def test_linux_inventory_reads_os_release(self):
        sys.path.insert(0, str(LINUX))
        try:
            import system_inventory as linux_system
            with patch.object(
                linux_system,
                "_os_release",
                return_value={
                    "NAME": "Ubuntu",
                    "PRETTY_NAME": "Ubuntu 24.04.4 LTS",
                    "VERSION_ID": "24.04",
                    "VERSION": "24.04.4 LTS (Noble Numbat)",
                },
            ), patch.object(linux_system.platform, "release", return_value="6.8.0-138-generic"), patch.object(
                linux_system.platform, "machine", return_value="x86_64"
            ):
                item = linux_system.collect_system_inventory()
            self.assertEqual(item["family"], "linux")
            self.assertEqual(item["pretty_name"], "Ubuntu 24.04.4 LTS")
            self.assertEqual(item["kernel"], "6.8.0-138-generic")
            self.assertEqual(item["architecture"], "x86_64")
        finally:
            sys.path.remove(str(LINUX))
            sys.modules.pop("system_inventory", None)

    def test_runtime_metrics_attach_system_inventory(self):
        windows = (WIN / "runtime_metrics.py").read_text(encoding="utf-8")
        linux = (LINUX / "runtime_metrics.py").read_text(encoding="utf-8")
        self.assertIn('telemetry["system"] = collect_system_inventory()', windows)
        self.assertIn('telemetry["system"] = collect_system_inventory()', linux)

    def test_dashboard_loads_system_renderer(self):
        html = (ROOT / "dashboard" / "web" / "agent-details.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "agent-system-details.js").read_text(encoding="utf-8")
        self.assertIn('agent-system-details.js?v=1', html)
        self.assertIn('telemetry.system', script)
        self.assertIn('Kernel ${kernel}', script)
        self.assertIn('Build ${build}', script)
        self.assertIn('Arquitetura ${architecture}', script)

    def test_dashboard_system_renderer_defends_against_legacy_overwrite_race(self):
        script = (ROOT / "dashboard" / "web" / "agent-system-details.js").read_text(encoding="utf-8")
        self.assertIn("let lastPayload = null", script)
        self.assertIn("new MutationObserver", script)
        self.assertIn("renderPayload(lastPayload)", script)
        self.assertIn('observer.observe(root, {childList: true, subtree: true, characterData: true})', script)


if __name__ == "__main__":
    unittest.main()
