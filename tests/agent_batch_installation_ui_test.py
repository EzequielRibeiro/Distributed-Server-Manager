#!/usr/bin/env python3
from __future__ import annotations
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentBatchInstallationUiTest(unittest.TestCase):
    def test_dashboard_exposes_batch_installation(self):
        index = (ROOT / "dashboard/web/add-agent.html").read_text(encoding="utf-8")
        page = (ROOT / "dashboard/web/add-agent-batch.html").read_text(encoding="utf-8")
        self.assertIn('href="add-agent-batch.html"', index)
        self.assertIn("Instalação em lote", index)
        self.assertEqual(page.count("data-batch-step-indicator"), 4)
        self.assertEqual(page.count("data-batch-step="), 4)
        self.assertIn('id="batch-test-all"', page)
        self.assertIn('id="batch-retry-failed"', page)
        self.assertIn('id="batch-ready-only"', page)
        self.assertIn('id="batch-install"', page)

    def test_batch_reuses_individual_preflight_install_and_status_contracts(self):
        js = (ROOT / "dashboard/web/agent-installation-batch.js").read_text(encoding="utf-8")
        self.assertIn('request("/agents/installations/test-connection"', js)
        self.assertIn('request("/agents/installations"', js)
        self.assertIn('/agents/installations/status?installation_id=', js)
        self.assertIn('method:"ssh"', js)
        self.assertIn('preflight === "ready"', js)
        self.assertIn('Promise.all(rows.map(testOne))', js)
        self.assertIn('Promise.all(rows.map(installOne))', js)
        self.assertNotIn('type="password"', (ROOT / "dashboard/web/add-agent-batch.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
