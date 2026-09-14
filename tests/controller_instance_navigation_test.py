#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class ControllerInstanceNavigationTest(unittest.TestCase):
    def test_manage_action_opens_instance_workspace_with_identity(self):
        script = (WEB / "servers.js").read_text(encoding="utf-8")

        self.assertIn(
            'href="controller-instance.html?${qs}">Gerenciar</a>',
            script,
        )
        self.assertNotIn("customer-instance.html?${qs}&auth_area=controller", script)
        self.assertNotIn(
            'class="cap-action-secondary" href="catalog.html">Gerenciar</a>',
            script,
        )
        self.assertIn(
            'new URLSearchParams({server:i.server,game:i.game,instance:i.instance})',
            script,
        )
        self.assertIn('["admin","controller"].includes(state.role)', script)
        self.assertIn('state.role=String(who.role||"").toLowerCase()', script)

    def test_controller_workspace_uses_controller_scoped_aliases(self):
        page = (WEB / "controller-instance.html").read_text(encoding="utf-8")

        adapter = page.index('<script src="/controller-instance-auth.js"></script>')
        workspace = page.index('<script src="/controller-instance-core.js"></script>')
        self.assertLess(adapter, workspace)
        for marker in (
            'href="/controller-instance-base.css"',
            'href="/controller-instance.css"',
            'src="/controller-instance-connection.js"',
            'src="/controller-instance-runtime-live.js"',
            'src="/controller-instance-backup-transfer.js"',
            'src="/controller-instance-activity.js"',
            'MODO ADMINISTRATIVO',
            'href="/servers.html"',
        ):
            self.assertIn(marker, page)
        self.assertNotIn('/customer-profile.js', page)
        self.assertNotIn('/customer-instance-delete.js', page)
        for view in ("overview", "console", "startup", "files", "content", "backups", "team", "activity"):
            self.assertIn(f'id="view-{view}"', page)
        for control in ("start", "restart", "stop"):
            self.assertIn(f'id="{control}"', page)
        css = (WEB / "controller-instance.css").read_text(encoding="utf-8")
        self.assertIn("#upgrade-tab", css)
        self.assertIn("#view-upgrade", css)
        self.assertIn(".danger-tab", css)
        self.assertIn("#view-danger", css)

    def test_customer_workspace_no_longer_loads_controller_adapter(self):
        page = (WEB / "customer-instance.html").read_text(encoding="utf-8")
        self.assertNotIn('/controller-instance-auth.js', page)

    def test_controller_adapter_preserves_controller_auth_domain(self):
        script = (WEB / "controller-instance-auth.js").read_text(encoding="utf-8")

        for token in (
            'location.pathname.endsWith("/controller-instance.html")',
            'params.get("auth_area")==="controller"',
            'headers.set("X-Capivara-Auth-Area","controller")',
            'location.replace("/login.html")',
            'back.href="/servers.html"',
            'logout.textContent="Voltar"',
        ):
            self.assertIn(token, script)

    def test_controller_workspace_is_registered_as_controller_surface(self):
        composition = (ROOT / "dashboard" / "server_part14.py").read_text(encoding="utf-8")
        policy = (ROOT / "dashboard" / "static_asset_policy.py").read_text(encoding="utf-8")
        guard = (ROOT / "dashboard" / "portal_navigation_session_http.py").read_text(encoding="utf-8")
        for route in (
            "/controller-instance.html",
            "/controller-instance-base.css",
            "/controller-instance.css",
            "/controller-instance-auth.js",
            "/controller-instance-core.js",
            "/controller-instance-connection.js",
            "/controller-instance-runtime-live.js",
            "/controller-instance-backup-transfer.js",
            "/controller-instance-activity.js",
        ):
            self.assertIn(f'"{route}"', composition)
            self.assertIn(f'"{route}"', policy)
        self.assertIn('"/controller-instance.html"', guard)

    def test_servers_asset_revision_is_bumped(self):
        page = (WEB / "servers.html").read_text(encoding="utf-8")
        self.assertIn('<script src="servers.js?v=9"></script>', page)


if __name__ == "__main__":
    unittest.main()
