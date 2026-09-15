#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = (ROOT / "dashboard/web/runtime-selector.js").read_text(encoding="utf-8")


class CustomerNeoForgeSelectorResilienceTest(unittest.TestCase):
    def test_catalog_requests_have_bounded_wait(self):
        self.assertIn("timeoutMs: 15000", SELECTOR)
        self.assertIn("A consulta ao catálogo excedeu o tempo limite.", SELECTOR)
        self.assertIn("new AbortController()", SELECTOR)

    def test_large_version_and_build_lists_render_atomically(self):
        self.assertIn("const versionOptions = document.createDocumentFragment();", SELECTOR)
        self.assertIn("el.version.replaceChildren(versionOptions);", SELECTOR)
        self.assertIn("const buildOptions = document.createDocumentFragment();", SELECTOR)
        self.assertIn("el.build.replaceChildren(buildOptions);", SELECTOR)


if __name__ == "__main__":
    unittest.main()
