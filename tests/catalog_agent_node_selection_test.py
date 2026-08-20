#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CatalogAgentNodeSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (ROOT / "dashboard/web/catalog-v2.js").read_text(encoding="utf-8")

    def test_catalog_loads_agents_independently_from_runtime_instances(self):
        self.assertIn('request("/api/runtime/list")', self.script)
        self.assertIn('request("/api/agents")', self.script)
        self.assertIn('state.agents =', self.script)

    def test_active_agent_nodes_are_combined_with_runtime_nodes(self):
        self.assertIn('function availableNodeIds()', self.script)
        self.assertIn('String(agent.status || "").toLowerCase() === "active"', self.script)
        self.assertIn('.map(agent => agent.node_id)', self.script)
        self.assertIn('unique([...runtimeNodes, ...agentNodes])', self.script)

    def test_zero_instances_do_not_hide_an_available_agent(self):
        self.assertIn('!state.resources.length && !availableNodeIds().length', self.script)
        self.assertNotIn('if (!state.resources.length) {\n                state.runtimes', self.script)

    def test_agent_lookup_failure_keeps_runtime_fallback(self):
        self.assertIn('request("/api/agents").catch(() => ({ agents: [] }))', self.script)
        self.assertIn('const runtimeNodes = state.resources.map(item => item.server);', self.script)


if __name__ == "__main__":
    unittest.main()
