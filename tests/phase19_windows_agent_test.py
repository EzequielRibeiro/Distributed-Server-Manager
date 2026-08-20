#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard", ROOT / "agents" / "windows" / "runtime"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from windows_agent_install_command import windows_agent_install_command
import network_inventory as windows_network_inventory


class Phase19WindowsAgentTest(unittest.TestCase):
    def test_install_command_uses_controller_bootstrap_and_only_pairing_secret(self):
        command = windows_agent_install_command(
            controller_url="https://controller.example",
            pairing_token="cap_pair_test-token",
        )
        self.assertIn("/agent/install.ps1", command)
        self.assertIn("cap_pair_test-token", command)
        self.assertNotIn("password", command.lower())
        self.assertNotIn("admin", command.lower())

    def test_windows_netstat_inventory_parses_tcp_and_udp(self):
        tcp = type("Completed", (), {"stdout": "  TCP    0.0.0.0:27015   0.0.0.0:0   LISTENING  123\n"})()
        udp = type("Completed", (), {"stdout": "  UDP    0.0.0.0:2302    *:*                  321\n"})()
        with patch("network_inventory.subprocess.run", side_effect=[tcp, udp]):
            inventory = windows_network_inventory.collect_network_inventory()
        self.assertEqual(inventory["tcp_listen"], [27015])
        self.assertEqual(inventory["udp_listen"], [2302])

    def test_windows_package_is_reproducible_and_manifest_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            one = Path(temporary) / "one"
            two = Path(temporary) / "two"
            subprocess.run([sys.executable, str(ROOT / "release" / "build_windows_agent_package.py"), "HEAD", str(one)], check=True)
            subprocess.run([sys.executable, str(ROOT / "release" / "build_windows_agent_package.py"), "HEAD", str(two)], check=True)
            version = (ROOT / "version").read_text(encoding="utf-8").strip()
            name = f"capivara-agent-windows-{version}.zip"
            archive_one = one / name
            archive_two = two / name
            self.assertEqual(archive_one.read_bytes(), archive_two.read_bytes())
            expected = (one / f"{name}.sha256").read_text(encoding="utf-8").split()[0]
            self.assertEqual(hashlib.sha256(archive_one.read_bytes()).hexdigest(), expected)
            with zipfile.ZipFile(archive_one) as package:
                root = f"capivara-agent-windows-{version}/"
                manifest = json.loads(package.read(root + "manifest.json"))
                self.assertEqual(manifest["platform"], "windows")
                self.assertEqual(manifest["kind"], "CapivaraAgentPackage")
                required = set(manifest["required_files"])
                for path in (
                    "install-agent.ps1",
                    "agent/common/identity.py",
                    "agent/runtime/agent.py",
                    "agent/runtime/capabilities.py",
                    "agent/runtime/network_inventory.py",
                    "agent/runtime/update_client.py",
                    "agent/updater/updater.py",
                    "service/register-task.ps1",
                ):
                    self.assertIn(path, required)
                    data = package.read(root + path)
                    self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["files"][path]["sha256"])

    def test_windows_and_linux_use_same_remote_protocol_paths(self):
        windows_runtime = (ROOT / "agents" / "windows" / "runtime" / "agent.py").read_text(encoding="utf-8")
        linux_runtime = (ROOT / "agents" / "linux" / "runtime" / "agent.py").read_text(encoding="utf-8")
        for path in ("/api/agent/enroll", "/api/agent/heartbeat"):
            self.assertIn(path, windows_runtime)
            self.assertIn(path, linux_runtime)
        for header in (
            "X-Capivara-Agent-Credential",
            "X-Capivara-Agent-Secret",
            "X-Capivara-Agent-Fingerprint",
        ):
            self.assertIn(header, windows_runtime)
            self.assertIn(header, linux_runtime)


if __name__ == "__main__":
    unittest.main()
