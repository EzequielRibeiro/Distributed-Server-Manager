#!/usr/bin/env python3
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CatalogAgentNodeSelectionTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.script=(ROOT/'dashboard/web/catalog-page.js').read_text(encoding='utf-8')
 def test_catalog_loads_agents_with_runtime_definitions(self):
  self.assertIn("request('/api/catalog/runtimes')",self.script);self.assertIn("request('/api/agents')",self.script);self.assertIn('state.agents=',self.script)
 def test_agent_selector_is_populated_from_agent_inventory(self):
  self.assertIn("setOptions(byId('catalog-agent'),state.agents",self.script);self.assertIn('selectedAgent()',self.script)
 def test_game_data_actions_target_selected_agent(self):
  self.assertIn("request('/api/agents/game-data'",self.script);self.assertIn('agent_id:agent',self.script);self.assertIn("/api/agents/game-data/inventory?agent_id=",self.script)
 def test_current_catalog_has_no_legacy_instance_content_mutation(self):
  for route in ('/api/catalog/install','/api/catalog/remove','/api/catalog/verify','/api/catalog/rollback','/api/catalog/installed'):self.assertNotIn(route,self.script)
if __name__=='__main__':unittest.main()
