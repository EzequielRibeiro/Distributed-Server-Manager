#!/usr/bin/env python3
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "agents" / "windows" / "runtime" / "agent_entrypoint.py"
LAUNCHER = ROOT / "agents" / "windows" / "service" / "run-agent.ps1"


class WindowsAgentUninstallEntrypointTest(unittest.TestCase):
    def test_entrypoint_is_syntax_valid_and_uses_typed_client(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("from uninstall_client import", source)
        self.assertIn("accept_command", source)
        self.assertIn("commit", source)
        self.assertIn('phase == "prepare"', source)
        self.assertIn('phase == "commit"', source)
        self.assertIn("raise SystemExit(0)", source)

    def test_inventory_publishes_uninstall_result(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn('payload["uninstall_result"] = result', source)

    def test_launcher_prefers_uninstall_aware_entrypoint(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("agent_entrypoint.py", source)
        self.assertIn("$scriptToRun", source)
        self.assertIn("Test-Path $entrypoint -PathType Leaf", source)


if __name__ == "__main__":
    unittest.main()
