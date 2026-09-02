#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
UPDATER_PATH = ROOT / "agents" / "linux" / "updater" / "updater.py"


def _load_updater():
    spec = importlib.util.spec_from_file_location("capivara_linux_updater_test", UPDATER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


updater = _load_updater()


class LinuxUpdaterUninstallParityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        self.install = self.root / "opt" / "capivara-agent"
        self.systemd = self.root / "etc" / "systemd" / "system"
        self.polkit = self.root / "etc" / "polkit-1" / "rules.d"

        for path in (
            self.package / "agent" / "runtime",
            self.package / "agent" / "common",
            self.package / "agent" / "privileged",
            self.package / "agent" / "policy",
            self.package / "agent" / "updater",
            self.package / "services",
        ):
            path.mkdir(parents=True, exist_ok=True)

        files = {
            "agent/runtime/agent.py": "print('agent')\n",
            "agent/common/identity.py": "# identity\n",
            "agent/privileged/materialize_instance.py": "# materialize\n",
            "agent/privileged/reconcile_runtime_identity.py": "# identity reconcile\n",
            "agent/privileged/uninstall_agent.py": "# uninstall executor\n",
            "agent/policy/49-capivara-agent-instance-units.rules": "// policy\n",
            "agent/updater/updater.py": "# updater\n",
            "services/capivara-agent-materialize@.service": "[Service]\n",
            "services/capivara-agent-runtime-identity.service": "[Service]\n",
            "services/capivara-agent-uninstall.path": "[Path]\n",
            "services/capivara-agent-uninstall.service": "[Service]\n",
            "manifest.json": "{}\n",
            "VERSION": "2.0.21\n",
        }
        for relative, content in files.items():
            path = self.package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        self.patchers = [
            mock.patch.object(updater, "INSTALL_ROOT", self.install),
            mock.patch.object(updater, "SYSTEMD_DIR", self.systemd),
            mock.patch.object(updater, "POLKIT_RULES_DIR", self.polkit),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_mapping_installs_uninstall_executor_and_units(self):
        mapping = updater._mapping(self.package)
        by_relative = {relative: (source, destination, mode) for source, destination, mode, relative in mapping}

        expected = {
            "agent/privileged/uninstall_agent.py": self.install / "privileged" / "uninstall_agent.py",
            "services/capivara-agent-uninstall.path": self.systemd / "capivara-agent-uninstall.path",
            "services/capivara-agent-uninstall.service": self.systemd / "capivara-agent-uninstall.service",
        }
        for relative, destination in expected.items():
            self.assertIn(relative, by_relative)
            self.assertEqual(destination, by_relative[relative][1])

        self.assertEqual(0o755, by_relative["agent/privileged/uninstall_agent.py"][2])
        self.assertEqual(0o644, by_relative["services/capivara-agent-uninstall.path"][2])
        self.assertEqual(0o644, by_relative["services/capivara-agent-uninstall.service"][2])

    def test_set_uninstall_watch_uses_systemd_enable_now(self):
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(updater.subprocess, "run", return_value=completed) as run:
            updater._set_uninstall_watch(True)

        run.assert_called_once_with(
            ["systemctl", "enable", "--now", "capivara-agent-uninstall.path"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_set_uninstall_watch_can_disable_during_rollback(self):
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(updater.subprocess, "run", return_value=completed) as run:
            updater._set_uninstall_watch(False)

        run.assert_called_once_with(
            ["systemctl", "disable", "--now", "capivara-agent-uninstall.path"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
