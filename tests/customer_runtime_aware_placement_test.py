from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = (ROOT / "dashboard/web/runtime-selector.js").read_text(encoding="utf-8")
PLACEMENT = (ROOT / "dashboard/web/customer-placement-client.js").read_text(encoding="utf-8")
HTML = (ROOT / "dashboard/web/customer.html").read_text(encoding="utf-8")


class CustomerRuntimeAwarePlacementTest(unittest.TestCase):
    def test_public_location_query_carries_runtime(self):
        self.assertIn('context.runtime || context.runtime_id', PLACEMENT)
        self.assertIn('params.set("runtime", runtime)', PLACEMENT)

    def test_runtime_selection_refreshes_location_eligibility(self):
        self.assertIn('runtime: runtimeId', SELECTOR)
        self.assertIn('loadRegions().catch', SELECTOR)
        self.assertNotIn('Promise.all([loadCatalog(game), loadRegions()])', SELECTOR)

    def test_stale_or_failed_placement_cannot_enable_creation(self):
        self.assertIn('placementRequestGeneration', SELECTOR)
        self.assertIn('placementAbortController', SELECTOR)
        self.assertIn('{signal: controller.signal}', SELECTOR)
        self.assertIn('state.placementReady = false', SELECTOR)
        self.assertIn('state.regions = []', SELECTOR)
        self.assertIn('el.submit.disabled = !state.placementReady', SELECTOR)

    def test_changed_assets_are_cache_busted(self):
        self.assertIn('/customer-placement-client.js?v=3', HTML)
        self.assertIn('/runtime-selector.js?v=10', HTML)


if __name__ == "__main__":
    unittest.main()
