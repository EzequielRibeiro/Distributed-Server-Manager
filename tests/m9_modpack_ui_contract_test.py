#!/usr/bin/env python3
from __future__ import annotations
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/"dashboard"/"web"/"customer-instance-v2.js"

class M9ModpackUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=UI.read_text(encoding="utf-8")

    def test_modpack_details_use_customer_safe_bundle_endpoint(self):
        text=self.text
        self.assertIn('/content/bundle?',text)
        self.assertIn('Ver conteúdo',text)
        self.assertIn('Ocultar conteúdo',text)
        self.assertIn('renderBundleDetails',text)

    def test_modpack_details_render_state_revision_and_diff(self):
        text=self.text
        for token in ('bundle.bundle_state==="customized"?"Personalizado":"Gerenciado"','bundle.current_revision','bundle.diff_from_previous','bundle.members','bundle.revisions'):
            self.assertIn(token,text)

    def test_modpack_update_is_previewed_before_mutation(self):
        self.assertIn('action:"preview-update"',self.text)
        self.assertIn("bundleDiffText(preview.manifest_diff)",self.text)
        self.assertIn("updateManagedContent(item)",self.text)

    def test_browser_does_not_render_artifact_authority_from_bundle_details(self):
        text=self.text
        block=text[text.index("function renderBundleDetails"):text.index("async function toggleBundleDetails")]
        for token in ("artifact","sha512","checksum","manifest_json","override_roots"):
            self.assertNotIn(token,block)

if __name__=="__main__":
    unittest.main()
