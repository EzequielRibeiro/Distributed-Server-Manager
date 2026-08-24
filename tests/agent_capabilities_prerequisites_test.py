#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import capabilities


class AgentCapabilitiesPrerequisitesTest(unittest.TestCase):
    def test_missing_32bit_runtime_is_reported_before_steamcmd_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            binary = state / "tools" / "steamcmd" / "steamcmd.sh"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"CAPIVARA_AGENT_STATE_DIR": str(state)}),
                patch.object(capabilities.platform, "machine", return_value="x86_64"),
                patch.object(capabilities.shutil, "which", return_value=None),
                patch.object(capabilities.Path, "exists", return_value=False),
            ):
                status = capabilities._steamcmd_status()
        self.assertTrue(status["installed"])
        self.assertFalse(status["functional"])
        self.assertFalse(status["runtime_32bit"])
        self.assertEqual(status["missing_dependencies"], ["linux-x86-32-runtime"])

    def test_installer_covers_common_linux_package_managers(self):
        installer = (ROOT / "agents/linux/installer/install-agent.sh").read_text(encoding="utf-8")
        for manager in ("apt-get", "dnf", "yum", "zypper"):
            self.assertIn(manager, installer)
        for dependency in ("libc6-i386", "lib32gcc-s1", "glibc.i686", "glibc-32bit"):
            self.assertIn(dependency, installer)


if __name__ == "__main__":
    unittest.main()
