#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class ControllerInstanceNavigationTest(unittest.TestCase):
    def test_manage_action_opens_instance_workspace_with_identity(self):
        script = (WEB / "servers.js").read_text(encoding="utf-8")

        self.assertIn(
            'href="customer-instance.html?${qs}&auth_area=controller">Gerenciar</a>',
            script,
        )
        self.assertNotIn(
            'class="cap-action-secondary" href="catalog.html">Gerenciar</a>',
            script,
        )
        self.assertIn(
            'new URLSearchParams({server:i.server,game:i.game,instance:i.instance})',
            script,
        )

    def test_workspace_loads_controller_adapter_before_customer_scripts(self):
        page = (WEB / "customer-instance.html").read_text(encoding="utf-8")

        adapter = page.index('<script src="/controller-instance-auth.js"></script>')
        workspace = page.index('<script src="/customer-instance-v2.js"></script>')
        self.assertLess(adapter, workspace)

    def test_controller_adapter_preserves_controller_auth_domain(self):
        script = (WEB / "controller-instance-auth.js").read_text(encoding="utf-8")

        for token in (
            'params.get("auth_area")!=="controller"',
            'headers.set("X-Capivara-Auth-Area","controller")',
            'location.replace("/login.html")',
            'back.href="/servers.html"',
            'logout.textContent="Voltar"',
        ):
            self.assertIn(token, script)

    def test_servers_asset_revision_is_bumped(self):
        page = (WEB / "servers.html").read_text(encoding="utf-8")
        self.assertIn('<script src="servers.js?v=8"></script>', page)


if __name__ == "__main__":
    unittest.main()
