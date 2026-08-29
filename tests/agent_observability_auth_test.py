#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dashboard" / "web" / "agent-observability.js"


class AgentObservabilityCookieAuthTest(unittest.TestCase):
    def test_observability_page_has_no_removed_legacy_auth_guard(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("if (!auth())", source)
        self.assertNotIn("sessionStorage", source)
        self.assertNotIn("Authorization", source)
        self.assertIn('"X-Capivara-Auth-Area":"controller"', source)
        self.assertIn('request("/api/whoami")', source)

    def test_missing_agent_id_fails_closed_to_agent_list(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('location.replace("agents.html?missing_agent=1")', source)
        self.assertIn('agent-details.html?agent_id=${encodeURIComponent(agentId)}', source)
        self.assertIn('agent-observability.html?agent_id=${encodeURIComponent(agentId)}&view=${targetView}', source)


if __name__ == "__main__":
    unittest.main()
