from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "dashboard" / "web" / "runtime-selector.js"
CUSTOMER_HTML = ROOT / "dashboard" / "web" / "customer.html"
WIZARD_CSS = ROOT / "dashboard" / "web" / "create-server-wizard.css"
RUNTIME_ICON_SPRITE = ROOT / "dashboard" / "web" / "assets" / "icons" / "runtime-sprite.svg"


class CustomerCatalogHierarchyTest(unittest.TestCase):
    def setUp(self):
        self.selector = SELECTOR.read_text(encoding="utf-8")
        self.customer_html = CUSTOMER_HTML.read_text(encoding="utf-8")
        self.wizard_css = WIZARD_CSS.read_text(encoding="utf-8")
        self.runtime_icon_sprite = RUNTIME_ICON_SPRITE.read_text(encoding="utf-8")

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
        self.assertIn('/runtime-selector.js?v=', self.customer_html)
        self.assertIn('/create-server-wizard.css?v=', self.customer_html)

    def test_runtime_cards_derive_capabilities_from_runtime_definition(self):
        self.assertIn('function runtimeCardCapabilities(runtime)', self.selector)
        self.assertIn('runtime?.content?.managed?.types', self.selector)
        self.assertIn('runtime?.content?.bundles', self.selector)
        self.assertIn('runtime?.network?.ports', self.selector)
        self.assertIn('const hasVotifierPort = ports.some', self.selector)
        self.assertIn('normalize(port?.name) === "votifier"', self.selector)
        self.assertIn('votifierMode = "Mod/Plugin"', self.selector)
        self.assertIn('votifierMode = "Plugin"', self.selector)
        self.assertIn('votifierMode = "Mod"', self.selector)
        self.assertIn('const votifier = Boolean(votifierMode)', self.selector)
        self.assertIn('["Mods", capabilities.mods]', self.selector)
        self.assertIn('["Plugins", capabilities.plugins]', self.selector)
        self.assertIn('["Modpacks", capabilities.modpacks]', self.selector)
        self.assertIn('Votifier · ${capabilities.votifierMode}', self.selector)

    def test_runtime_distribution_cards_have_responsive_visual_contract(self):
        self.assertIn('runtime-distribution-card', self.selector)
        self.assertIn('runtime-card-mark', self.selector)
        self.assertIn('runtime-card-icon', self.selector)
        self.assertIn('runtime-capabilities', self.selector)
        self.assertIn('.runtime-distribution-card', self.wizard_css)
        self.assertIn('.runtime-capability.supported', self.wizard_css)
        self.assertIn('.runtime-capability.unsupported', self.wizard_css)
        self.assertIn('#runtime-types.runtime-selector-grid', self.wizard_css)

    def test_runtime_cards_are_gated_by_contract_policy(self):
        self.assertIn('function contractAllowsRuntime(runtimeId)', self.selector)
        self.assertIn('state.contract?.allowed_runtime_ids', self.selector)
        self.assertIn('button.disabled = !allowed', self.selector)
        self.assertIn('contract-blocked', self.selector)
        self.assertIn('Exige Minecraft Modificado', self.selector)
        self.assertIn('.runtime-card-contract-note', self.wizard_css)

    def test_contract_gate_runs_before_runtime_selection(self):
        self.assertIn('if (!contractAllowsRuntime(runtime?.id))', self.selector)
        self.assertIn('showMessage(contractRuntimeMessage())', self.selector)


    def test_runtime_cards_use_inline_vector_icons(self):
        self.assertIn('function runtimeCardIconId(distribution, runtime)', self.selector)
        self.assertIn('function runtimeCardIconMarkup(iconId)', self.selector)
        self.assertIn('document.createElementNS("http://www.w3.org/2000/svg", "svg")', self.selector)
        self.assertIn('icon.innerHTML = runtimeCardIconMarkup(', self.selector)
        self.assertNotIn('RUNTIME_ICON_SPRITE =', self.selector)
        self.assertNotIn('use.setAttribute("href"', self.selector)
        for icon_id in (
            "runtime-vanilla",
            "runtime-fabric",
            "runtime-forge",
            "runtime-neoforge",
            "runtime-quilt",
            "runtime-paper",
            "runtime-purpur",
            "runtime-folia",
            "runtime-spongevanilla",
            "runtime-arclight",
            "runtime-youer",
            "runtime-bedrock",
            "runtime-default",
        ):
            self.assertIn(f'"{icon_id}"', self.selector)



if __name__ == "__main__":
    unittest.main()
