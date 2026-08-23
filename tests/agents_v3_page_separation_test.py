#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard/web"


class AgentsV3PageSeparationTest(unittest.TestCase):
    def test_fleet_page_stays_compact(self):
        html = (WEB / "agents.html").read_text(encoding="utf-8")
        self.assertIn("Frota de Agents", html)
        self.assertIn('id="agents-list"', html)
        self.assertNotIn("Telemetria do computador", html)
        self.assertNotIn('id="agent-install-form"', html)

    def test_add_agent_has_its_own_navigation_entry(self):
        sidebar = (WEB / "components/sidebar-v3.html").read_text(encoding="utf-8")
        self.assertIn('href="add-agent.html"', sidebar)
        self.assertIn("Adicionar Agent", sidebar)

    def test_detail_page_exists_and_links_back(self):
        detail = (WEB / "agent-details.html").read_text(encoding="utf-8")
        self.assertIn('href="agents.html"', detail)
        self.assertIn("Portas administradas", detail)
        self.assertIn("Localização e Placement", detail)


if __name__ == "__main__":
    unittest.main()
