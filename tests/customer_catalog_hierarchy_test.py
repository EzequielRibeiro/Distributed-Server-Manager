from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "dashboard" / "web" / "runtime-selector.js"
CUSTOMER_HTML = ROOT / "dashboard" / "web" / "customer.html"


class CustomerCatalogHierarchyTest(unittest.TestCase):
    def setUp(self):
        self.selector = SELECTOR.read_text(encoding="utf-8")
        self.customer_html = CUSTOMER_HTML.read_text(encoding="utf-8")

    def test_selector_uses_canonical_hierarchy_for_discovery(self):
        self.assertIn('/api/catalog/hierarchy?game=', self.selector)
        self.assertIn('catalogGame.editions', self.selector)
        self.assertIn('edition.distributions', self.selector)
        self.assertIn('distribution.runtime_definitions', self.selector)

    def test_flat_runtime_endpoint_is_hydration_only(self):
        self.assertIn('placementClient().loadRuntimes(game)', self.selector)
        self.assertIn('runtimeById', self.selector)
        self.assertNotIn('function runtimeEdition(', self.selector)
        self.assertNotIn('matchingRuntimes()', self.selector)

    def test_creation_keeps_canonical_runtime_id_and_distribution(self):
        self.assertIn('runtime_id: state.runtime.id', self.selector)
        self.assertIn('variant: state.distribution', self.selector)
        self.assertIn('distribution: state.distribution', self.selector)

    def test_customer_ui_names_distribution_step(self):
        self.assertIn('<strong>Distribuição</strong>', self.customer_html)
        self.assertIn('Distribuição Minecraft', self.customer_html)
        self.assertIn('/runtime-selector.js?v=4', self.customer_html)


if __name__ == "__main__":
    unittest.main()
