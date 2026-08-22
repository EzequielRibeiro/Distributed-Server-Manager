#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HelpCenterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web = ROOT / "dashboard" / "web"
        cls.html = (web / "help.html").read_text(encoding="utf-8")
        cls.javascript = (web / "help.js").read_text(encoding="utf-8")
        cls.sidebar = (web / "components" / "sidebar.html").read_text(encoding="utf-8")
        cls.server = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
        cls.ssh_tutorial = (
            ROOT / "docs" / "tutorial-instalacao-agent-via-ssh.md"
        ).read_text(encoding="utf-8")

    def test_help_page_has_search_and_subject_menu(self):
        self.assertIn('id="help-search"', self.html)
        self.assertIn('data-help-category="agents"', self.html)
        self.assertIn('data-help-category="games"', self.html)
        self.assertIn('data-help-category="operations"', self.html)
        self.assertIn('aria-live="polite"', self.html)

    def test_help_catalog_includes_every_operational_tutorial(self):
        tutorials = sorted((ROOT / "docs").glob("tutorial-*.md"))
        self.assertGreaterEqual(len(tutorials), 2)
        for tutorial in tutorials:
            self.assertIn(tutorial.name, self.javascript)

    def test_ssh_tutorial_covers_service_identity_and_preflight(self):
        for contract in (
            "systemctl show dsm-dashboard.service -p User --value",
            "id_ed25519",
            "ssh-copy-id",
            "BatchMode=yes",
            "StrictHostKeyChecking=accept-new",
            "NOPASSWD: /usr/bin/true, /usr/bin/python3 -",
            "SSH_OK",
        ):
            self.assertIn(contract, self.ssh_tutorial)

    def test_help_assets_are_authenticated_static_routes(self):
        for route in ("/help.html", "/help.css", "/help.js"):
            self.assertIn(f'"{route}"', self.server)
        public_block = self.server.split("public_files =", 1)[1].split("if path in public_files", 1)[0]
        self.assertNotIn("/help.html", public_block)
        self.assertIn('href="help.html"', self.sidebar)


if __name__ == "__main__":
    unittest.main()
