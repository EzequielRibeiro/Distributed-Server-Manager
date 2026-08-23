#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "dashboard/web/dashboard-home-v3.css").read_text(encoding="utf-8")
SIDEBARS = [
    (ROOT / "dashboard/web/components/sidebar.html").read_text(encoding="utf-8"),
    (ROOT / "dashboard/web/components/sidebar-v3.html").read_text(encoding="utf-8"),
]

assert "body.cap-home.cap-sidebar-collapsed #sidebar-component" in CSS
assert "body.cap-home.sidebar-open #sidebar-component" in CSS
assert "body.cap-home.cap-sidebar-collapsed .cap-home-main" in CSS
assert "body.cap-home.sidebar-open .cap-home-main" in CSS
assert "body.cap-home.cap-sidebar-collapsed::before" in CSS
assert "overflow-x:hidden" in CSS

for sidebar in SIDEBARS:
    assert 'href="catalog.html" class="instance-manager-only"' not in sidebar
    assert '<span>Criar instância</span>' not in sidebar
    assert '<span>Catálogo de jogos</span>' in sidebar

print("dashboard v3 mobile drawer contract: OK")
