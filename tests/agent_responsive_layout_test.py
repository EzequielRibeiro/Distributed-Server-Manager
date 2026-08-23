#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentResponsiveLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "dashboard/web/agents.css").read_text(encoding="utf-8")
        cls.shell = (ROOT / "dashboard/web/dashboard-ui-v2.css").read_text(encoding="utf-8")

    def test_agents_page_does_not_reserve_sidebar_twice(self):
        self.assertIn("padding-left: var(--cap-sidebar);", self.shell)
        self.assertIn(".agents-main {", self.css)
        self.assertIn("margin-left: 0;", self.css)
        self.assertIn("max-width: 100%;", self.css)

    def test_agent_grids_can_shrink_inside_viewport(self):
        self.assertIn("minmax(min(280px, 100%), 1fr)", self.css)
        self.assertIn("minmax(min(240px, 100%), 1fr)", self.css)
        self.assertIn("min-width: 0;", self.css)

    def test_wide_process_table_scrolls_inside_panel_not_page(self):
        self.assertIn(".agent-process-panel {", self.css)
        self.assertIn("overflow-x: auto;", self.css)
        self.assertIn("overscroll-behavior-inline: contain;", self.css)

    def test_mobile_header_actions_can_wrap(self):
        self.assertIn("flex-wrap: wrap;", self.css)
        self.assertIn("@media (max-width: 680px)", self.css)
        self.assertIn("flex: 1 1 140px;", self.css)


if __name__ == "__main__":
    unittest.main()
