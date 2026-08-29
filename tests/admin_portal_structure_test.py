#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
WEB = DASHBOARD / "web"


class AdminPortalStructureTest(unittest.TestCase):
    def source(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def test_dashboard_quick_actions_have_dedicated_routes(self):
        html = self.source(WEB / "dashboard-v3.html")
        self.assertIn('href="customer-create.html"', html)
        self.assertIn('href="customer-contract-create.html"', html)

    def test_controller_static_assets_are_area_guarded(self):
        source = self.source(DASHBOARD / "portal_navigation_session_http.py")
        for asset in (
            "/components/sidebar-v3.html",
            "/dashboard-home-v3.css",
            "/dashboard-node-overview.css",
            "/dashboard-node-overview.js",
            "/catalog-page.css",
            "/catalog-page.js",
            "/game-profiles.css",
            "/game-profiles.js",
            "/system.js",
            "/observability.js",
            "/infrastructure-v3.js",
        ):
            self.assertIn(f'"{asset}"', source)
        self.assertIn('area="controller"', source)

    def test_dashboard_node_activity_surface_is_scalable_and_navigable(self):
        html = self.source(WEB / "dashboard-v3.html")
        source = self.source(WEB / "dashboard-node-overview.js")
        self.assertIn('Players na infraestrutura', html)
        self.assertIn('Nodes — atividade em tempo real', html)
        self.assertIn('id="home-node-page-size"', html)
        self.assertIn('data-sort="players"', html)
        self.assertIn('agent-details.html?agent_id=', source)
        self.assertIn('servers.html?agent=', source)
        self.assertIn('agent-observability.html?agent_id=', source)
        self.assertIn('diagnostics.html?agent_id=', source)
        self.assertIn('controller-logs.html?agent_id=', source)
        self.assertIn('BUCKET_MS=300000', source)
        self.assertIn('DAY_MS=86400000', source)
        self.assertIn('window.setInterval(load,30000)', source)
        self.assertIn('X-Capivara-Auth-Area', source)

    def test_operations_menu_only_exposes_implemented_destinations(self):
        sidebar = self.source(WEB / "components" / "sidebar-v3.html")
        operations = self.source(WEB / "operations.html")
        script = self.source(WEB / "operations.js")
        self.assertIn('href="operations.html"><span class="cap-nav-icon">◉</span><span>Backups</span>', sidebar)
        self.assertIn('href="agents.html#agent-update-panel"', sidebar)
        self.assertNotIn('operations.html#scheduler', sidebar)
        self.assertNotIn('operations.html#updates', sidebar)
        self.assertNotIn('id="scheduler"', operations)
        self.assertNotIn('/api/scheduler', script)
        self.assertIn('/components/sidebar-v3.html', script)

    def test_agent_rollout_version_uses_compatible_release_catalog(self):
        html = self.source(WEB / "agents.html")
        script = self.source(WEB / "agent-updates-v3.js")
        api = self.source(DASHBOARD / "agent_update_api.py")
        self.assertIn('<select id="agent-rollout-version"', html)
        self.assertNotIn('id="agent-rollout-version" type="text"', html)
        self.assertIn('release_catalog', script)
        self.assertIn('channel === "stable" ? catalog.filter(item => !item.prerelease) : catalog', script)
        self.assertIn('O canal Local / manual não utiliza o catálogo remoto de releases.', script)
        self.assertIn('list_agent_releases', api)
        self.assertIn('AgentRuntimeRepository', api)
        self.assertIn('include_prereleases=True', api)

    def test_servers_page_loads_sidebar_with_controller_session(self):
        html = self.source(WEB / "servers.html")
        source = self.source(WEB / "servers.js")
        self.assertIn('id="sidebar-component"', html)
        self.assertIn('servers.js?v=7', html)
        self.assertIn('fetch("components/sidebar-v3.html",{headers:controllerHeaders()', source)
        self.assertIn('credentials:"same-origin"', source)
        self.assertIn('"X-Capivara-Auth-Area":"controller"', source)
        self.assertNotIn('if(!auth())', source)

    def test_catalog_and_profiles_keep_full_admin_layout_styles(self):
        catalog = self.source(WEB / "catalog.html")
        profiles = self.source(WEB / "game-profiles.html")
        self.assertIn('/dashboard-home-v3.css', catalog)
        self.assertIn('/catalog-page.css', catalog)
        self.assertIn('id="sidebar-component"', catalog)
        self.assertIn('/dashboard-home-v3.css', profiles)
        self.assertIn('/game-profiles.css', profiles)
        self.assertIn('id="sidebar-component"', profiles)

    def test_system_hashes_select_distinct_sections_and_fail_closed_loading(self):
        source = self.source(WEB / "system.js")
        self.assertIn('new Set(["configuration","api-security","audit"])', source)
        self.assertIn('window.addEventListener("hashchange",applySection)', source)
        self.assertIn('section.hidden=section.id!==selected', source)
        self.assertIn('Auditoria indisponível no momento.', source)

    def test_observability_uses_existing_admin_diagnostics_and_log_routes(self):
        source = self.source(WEB / "observability.js")
        self.assertIn('doctor=await get("/admin/observability")', source)
        self.assertIn('get(`/log-viewer?', source)
        self.assertNotIn('get("/infrastructure/doctor")', source)
        self.assertIn('Logs do Controller indisponíveis', source)

    def test_controller_telemetry_uses_controller_authenticator(self):
        source = self.source(DASHBOARD / "server_part17.py")
        self.assertIn('user=_controller_authenticate(self.headers)', source)
        self.assertNotIn('user=_authenticate(self.headers)', source)

    def test_infrastructure_lists_registered_datacenters_but_excludes_inactive_from_placement(self):
        source = self.source(WEB / "infrastructure-v3.js")
        self.assertIn('entities(data,"datacenters","datacenter")', source)
        self.assertIn('active_only=${includeInactive?"false":"true"}', source)
        self.assertIn('datacenters.filter(dc=>statusOf(dc)?.ok!==false)', source)

    def test_dashboard_never_leaves_telemetry_loading_forever(self):
        source = self.source(WEB / "dashboard-home-v3.js")
        self.assertIn('Telemetria do Controller indisponível no momento.', source)
        self.assertIn('Componente de telemetria indisponível.', source)


if __name__ == "__main__":
    unittest.main()
