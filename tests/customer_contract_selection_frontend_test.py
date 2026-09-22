#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "dashboard" / "web" / "customer.js").read_text(encoding="utf-8")


class CustomerContractSelectionFrontendTest(unittest.TestCase):
    def test_contract_cards_show_product_variant(self):
        self.assertIn("function contractProductLabel(contract)", SCRIPT)
        self.assertIn("Minecraft Modificado", SCRIPT)
        self.assertIn("Minecraft Padrão", SCRIPT)
        self.assertIn('product.className =\n      "contract-product"', SCRIPT)

    def test_catalog_does_not_silently_choose_first_of_multiple_contracts(self):
        self.assertIn("const availableContracts =", SCRIPT)
        self.assertIn("availableContracts.length ===\n              1", SCRIPT)
        self.assertIn("availableContracts[0]", SCRIPT)
        self.assertIn("Há ${availableContracts.length} contratos disponíveis", SCRIPT)
        self.assertNotIn("const contract =\n              contracts.find(", SCRIPT)


if __name__ == "__main__":
    unittest.main()
