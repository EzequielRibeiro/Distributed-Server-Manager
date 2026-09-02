#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "dashboard" / "web" / "agent-uninstall-admin.js"
HTML = ROOT / "dashboard" / "web" / "agent-details.html"


class AgentDestructiveTargetGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = JS.read_text(encoding="utf-8")
        cls.html = HTML.read_text(encoding="utf-8")

    def test_destructive_actions_verify_loaded_target(self):
        self.assertIn("async function verifyDestructiveTarget()", self.js)
        self.assertIn('el("detail-agent-id")', self.js)
        self.assertIn('/api/admin/agent?agent_id=', self.js)
        self.assertIn("backendAgentId !== agentId", self.js)

    def test_node_identity_is_cross_checked(self):
        self.assertIn('el("detail-node")', self.js)
        self.assertIn("displayedNodeId !== backendNodeId", self.js)

    def test_uninstall_uses_verified_agent(self):
        self.assertIn("agent_id: expected.agent_id", self.js)
        self.assertIn("assertMutationResponse(result, expected)", self.js)

    def test_force_remove_uses_same_guard(self):
        force_remove = self.js.split("async function forceRemove()", 1)[1]
        self.assertIn("expected = await verifyDestructiveTarget()", force_remove)
        self.assertIn("assertMutationResponse(result, expected)", force_remove)

    def test_state_polling_rejects_other_agent(self):
        self.assertIn('String(result.agent_id || "") !== agentId', self.js)

    def test_html_cache_busts_hardened_script(self):
        self.assertIn('agent-uninstall-admin.js?v=4', self.html)


if __name__ == "__main__":
    unittest.main()
