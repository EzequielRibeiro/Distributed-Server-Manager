#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class SidebarGlobalContractTest(unittest.TestCase):

    def test_every_sidebar_page_loads_global_controller(self):
        pages = []

        for path in sorted(WEB.glob("*.html")):
            text = path.read_text(encoding="utf-8")

            if "sidebar-component" not in text:
                continue

            pages.append(path.name)

            self.assertIn(
                "/sidebar-v3.js?v=2",
                text,
                f"{path.name} não carrega o controlador global",
            )

        self.assertGreaterEqual(len(pages), 20)

    def test_global_controller_has_complete_mobile_contract(self):
        js = (WEB / "sidebar-v3.js").read_text(encoding="utf-8")

        required = (
            "sidebar-open",
            "cap-sidebar-collapsed",
            "cap-sidebar-open",
            "pointerdown",
            "touchstart",
            "touchend",
            "dx < -60",
            "Escape",
            "stopImmediatePropagation",
            "aria-expanded",
            "localStorage",
            "CapivaraSidebar",
        )

        for marker in required:
            self.assertIn(marker, js)

    def test_sidebar_has_explicit_close_control(self):
        for name in ("sidebar-v3.html", "sidebar.html"):
            text = (
                WEB / "components" / name
            ).read_text(encoding="utf-8")

            self.assertIn("cap-sidebar-close", text)
            self.assertIn('aria-label="Fechar menu"', text)

    def test_static_route_is_registered(self):
        composition = (
            ROOT / "dashboard" / "server_part14.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '"/sidebar-v3.js": legacy.WEB_DIR / "sidebar-v3.js"',
            composition,
        )


if __name__ == "__main__":
    unittest.main()
