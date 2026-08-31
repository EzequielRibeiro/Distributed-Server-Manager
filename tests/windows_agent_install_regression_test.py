#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WindowsAgentInstallRegressionTest(unittest.TestCase):
    def test_dashboard_resolves_latest_before_remote_bootstrap(self):
        source = (ROOT / "dashboard/agent_installation_api.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'requested=str(payload.get("release_tag") or "latest").strip()',
            source,
        )
        self.assertIn(
            "release=resolve_agent_release(requested,platform)",
            source,
        )
        self.assertIn('release_tag=str(release["tag"])', source)
        self.assertNotIn('else: release_tag="latest"', source)

    def test_windows_installer_does_not_execute_python_with_dash_c(self):
        source = (ROOT / "agents/windows/installer/install-agent.ps1").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("& $python -c $verify", source)
        self.assertNotIn("& $python -c $identityCode", source)
        self.assertIn("verify-package.py", source)
        self.assertIn("generate-identity.py", source)


if __name__ == "__main__":
    unittest.main()
