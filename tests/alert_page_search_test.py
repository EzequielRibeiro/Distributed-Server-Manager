#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard", ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from alert_management_http import alert_matches_query


class AlertPageSearchTest(unittest.TestCase):
    def test_search_matches_supported_alert_fields(self) -> None:
        alert = {
            "id": "agent-identity-abc123",
            "rule_id": "agent.identity_collision",
            "level": "CRITICAL",
            "state": "ACKNOWLEDGED",
            "message": "Identidade lógica duplicada",
            "agent_id": "agent-42",
            "instance_id": "instance-7",
        }
        for query in (
            "abc123",
            "IDENTITY_COLLISION",
            "critical",
            "acknowledged",
            "duplicada",
            "agent-42",
            "instance-7",
        ):
            with self.subTest(query=query):
                self.assertTrue(alert_matches_query(alert, query))
        self.assertFalse(alert_matches_query(alert, "nao-existe"))

    def test_alerts_page_contains_search_scope_and_identifier_support(self) -> None:
        html = (ROOT / "dashboard" / "web" / "alerts.html").read_text(encoding="utf-8")
        enhancement = (
            ROOT / "dashboard" / "web" / "alerts-page-enhancements.js"
        ).read_text(encoding="utf-8")
        self.assertIn('id="alert-search"', html)
        self.assertIn('id="alert-agent-scope"', html)
        self.assertIn('id="alert-agent-scope-clear"', html)
        self.assertIn('type="button">Mostrar todos os Agents</button>', html)
        self.assertIn("border-top:1px solid rgba(255,255,255,.1)", html)
        self.assertIn("cap-alert-agent-id", html)
        self.assertIn("cap-alert-agent-id", enhancement)
        self.assertIn("ID do alerta: ${id}", enhancement)
        self.assertIn("ID do Agent: ${currentAgentId}", enhancement)
        self.assertIn("cap-alert-control-link", enhancement)
        self.assertIn("button[data-agent-href]", enhancement)
        self.assertIn("column-gap:10px!important", html)
        self.assertIn("margin-top:14px", html)
        self.assertIn('url.searchParams.set("agent_id", agentId)', enhancement)
        self.assertIn('url.searchParams.set("q", query)', enhancement)

    def test_agent_details_has_alert_shortcut(self) -> None:
        html = (ROOT / "dashboard" / "web" / "agent-details.html").read_text(encoding="utf-8")
        binder = (ROOT / "dashboard" / "web" / "agent-alert-link.js").read_text(encoding="utf-8")
        self.assertIn('id="agent-alerts-link"', html)
        self.assertIn('alerts.html?agent_id=', binder)


if __name__ == "__main__":
    unittest.main()
