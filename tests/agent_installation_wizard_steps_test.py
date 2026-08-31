#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentInstallationWizardStepsTest(unittest.TestCase):
    def test_linux_and_windows_use_four_semantic_steps(self):
        for name in ("add-agent-linux.html", "add-agent-windows.html"):
            html = (ROOT / "dashboard/web" / name).read_text(encoding="utf-8")
            self.assertEqual(html.count('class="cap-agent-step"'), 4)
            self.assertEqual(html.count("data-agent-step-indicator"), 4)
            self.assertIn('id="agent-step-prev"', html)
            self.assertIn('id="agent-step-next"', html)
            self.assertIn('id="agent-install-review"', html)
            self.assertIn('id="agent-release-anchor"', html)

    def test_wizard_validates_before_advancing_and_reviews_before_submit(self):
        js = (ROOT / "dashboard/web/agent-installation-wizard.js").read_text(encoding="utf-8")
        self.assertIn("function validateStep(index)", js)
        self.assertIn("if (!validateStep(currentStep)) return", js)
        self.assertIn("function showStep(index)", js)
        self.assertIn("function renderReview()", js)
        self.assertIn("first?.focus", js)
        self.assertIn("Informe a URL do Controller alcançável pelo Agent", js)
        self.assertIn("sshUrl.required = ssh", js)
        self.assertIn("winrmUrl.required = winrm", js)
        self.assertNotIn('el("agent-controller-url").value = window.location.origin', js)
        self.assertNotIn('el("agent-winrm-controller-url").value = window.location.origin', js)


if __name__ == "__main__":
    unittest.main()
