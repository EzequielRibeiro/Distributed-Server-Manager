#!/usr/bin/env python3

import re
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CUSTOMER_HTML = (
    ROOT
    / "dashboard"
    / "web"
    / "customer.html"
)

RUNTIME_SELECTOR_JS = (
    ROOT
    / "dashboard"
    / "web"
    / "runtime-selector.js"
)


class CustomerRuntimeSelectorContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.html = CUSTOMER_HTML.read_text(
            encoding="utf-8"
        )

        cls.javascript = (
            RUNTIME_SELECTOR_JS.read_text(
                encoding="utf-8"
            )
        )

        cls.html_ids = re.findall(
            r'\bid=["\']([^"\']+)["\']',
            cls.html,
        )

        cls.javascript_ids = sorted(
            set(
                re.findall(
                    r'\$\("([^"]+)"\)',
                    cls.javascript,
                )
            )
        )

    def test_runtime_selector_elements_exist_in_customer_html(
        self,
    ):
        html_ids = set(
            self.html_ids
        )

        missing = [
            element_id
            for element_id
            in self.javascript_ids
            if element_id not in html_ids
        ]

        self.assertEqual(
            missing,
            [],
            (
                "runtime-selector.js referencia IDs "
                "ausentes em customer.html: "
                f"{missing}"
            ),
        )

    def test_customer_html_has_no_duplicate_ids(
        self,
    ):
        counts = Counter(
            self.html_ids
        )

        duplicates = sorted(
            element_id
            for element_id, count
            in counts.items()
            if count > 1
        )

        self.assertEqual(
            duplicates,
            [],
            (
                "customer.html possui IDs "
                "duplicados: "
                f"{duplicates}"
            ),
        )

    def test_region_step_contract_is_complete(
        self,
    ):
        required = {
            "runtime-region-step",
            "runtime-region",
            "runtime-region-help",
            "runtime-region-fallback",
            "runtime-summary-region",
            "runtime-summary-region-fallback",
        }

        html_ids = set(
            self.html_ids
        )

        missing = sorted(
            required - html_ids
        )

        self.assertEqual(
            missing,
            [],
            (
                "Contrato da etapa Região "
                "está incompleto: "
                f"{missing}"
            ),
        )

    def test_runtime_selector_uses_region_elements(
        self,
    ):
        required_references = {
            "runtime-region-step",
            "runtime-region",
            "runtime-region-help",
            "runtime-region-fallback",
        }

        javascript_ids = set(
            self.javascript_ids
        )

        missing = sorted(
            required_references
            - javascript_ids
        )

        self.assertEqual(
            missing,
            [],
            (
                "runtime-selector.js não utiliza "
                "todos os elementos da Região: "
                f"{missing}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
