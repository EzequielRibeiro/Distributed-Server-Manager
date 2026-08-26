#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AgentQueueDetailsPersistenceTest(unittest.TestCase):
    def test_observability_page_loads_queue_state_helper(self):
        html = (ROOT / "dashboard" / "web" / "agent-observability.html").read_text(encoding="utf-8")
        self.assertIn("agent-queue-details-state.js?v=1", html)
        self.assertLess(html.index("agent-observability.js"), html.index("agent-queue-details-state.js"))

    def test_queue_state_is_scoped_per_agent_and_storage_is_guarded(self):
        script = (ROOT / "dashboard" / "web" / "agent-queue-details-state.js").read_text(encoding="utf-8")
        self.assertIn('params.get("agent_id")', script)
        self.assertIn("capivara.agent.queue-details-open.", script)
        self.assertIn("encodeURIComponent(agentId)", script)
        self.assertIn("window.localStorage.getItem", script)
        self.assertIn("window.localStorage.setItem", script)
        self.assertGreaterEqual(script.count("try {"), 2)
        self.assertGreaterEqual(script.count("catch (_error)"), 2)

    def test_refresh_replacement_is_observed_and_default_remains_collapsed(self):
        script = (ROOT / "dashboard" / "web" / "agent-queue-details-state.js").read_text(encoding="utf-8")
        self.assertIn("MutationObserver", script)
        self.assertIn("childList: true", script)
        self.assertIn("subtree: true", script)
        self.assertIn('preference === "1"', script)
        self.assertIn('preference === "0"', script)
        self.assertNotIn("details.open = true;\n            details.addEventListener", script)

    def test_only_queue_details_are_bound(self):
        script = (ROOT / "dashboard" / "web" / "agent-queue-details-state.js").read_text(encoding="utf-8")
        self.assertIn('.cap-agent-queue-summary > details', script)
        self.assertIn('details.dataset.queueStateBound', script)
        self.assertIn('details.addEventListener("toggle"', script)


if __name__ == "__main__":
    unittest.main()
