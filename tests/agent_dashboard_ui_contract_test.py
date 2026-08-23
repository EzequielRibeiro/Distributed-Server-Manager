#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentDashboardUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web = ROOT / "dashboard/web"
        cls.html = (web / "agents.html").read_text(encoding="utf-8")
        cls.install = (web / "agent-installation.js").read_text(encoding="utf-8")
        cls.location = (web / "agent-location-ui.js").read_text(encoding="utf-8")
        cls.updates = (web / "agent-updates.js").read_text(encoding="utf-8")
        cls.sidebar = (web / "components/sidebar-v3.html").read_text(encoding="utf-8")
        cls.servers_html = (web / "servers.html").read_text(encoding="utf-8")
        cls.servers_js = (web / "servers.js").read_text(encoding="utf-8")
        cls.infrastructure_ui = (web / "infrastructure-ui-v2.js").read_text(encoding="utf-8")
        cls.topology = (web / "infrastructure-topology-v2.js").read_text(encoding="utf-8")
        cls.service = (ROOT / "systemd/dsm-dashboard.service").read_text(encoding="utf-8")

    def test_add_agent_controls_are_present(self):
        for text in ("Adicionar Agent", "Linux", "Windows", "GitHub Release", "Pacote local", "Região", "Datacenter", "Gerar instalação"):
            self.assertIn(text, self.html)

    def test_installation_progress_states_are_present(self):
        for text in ("Aguardando Agent", "Pareando", "Validando", "Online"):
            self.assertIn(text, self.html)
        self.assertIn("/agents/installations", self.install)
        self.assertIn("/agents/installations/status", self.install)

    def test_location_controls_include_region_and_safety_message(self):
        for value in ('id="agent-region"','id="agent-datacenter"','id="agent-public-host"','id="agent-latitude"','id="agent-longitude"'):
            self.assertIn(value, self.html)
        self.assertIn("Instâncias existentes permanecem vinculadas ao Agent", self.html)
        self.assertIn("region_id", self.location)

    def test_remote_update_controls_and_batch_contract_are_present(self):
        for text in ("Versão instalada", "Versão disponível", "Tamanho do lote", "Stable", "Beta", "Local / manual"):
            self.assertIn(text, self.html)
        self.assertIn("/agents/updates/rollouts", self.updates)
        self.assertIn("/agents/updates/status", self.updates)
        self.assertIn("batch_size", self.updates)

    def test_phase_assets_and_current_entrypoint_are_loaded(self):
        for asset in ('/agent-installation.js','/agent-location-ui.js','/agent-updates.js','/infrastructure-ui-v2.js','/infrastructure-topology-v2.js'):
            self.assertIn(asset, self.html)
        self.assertIn('dashboard/server_part14.py', self.service)

    def test_dashboard_v3_navigation_preserves_rbac_classes(self):
        self.assertIn('href="servers.html"', self.sidebar)
        self.assertIn('href="agents.html"', self.sidebar)
        for role_class in ('admin-only','agent-manager-only','instance-manager-only'):
            self.assertIn(role_class, self.sidebar)
        self.assertIn('href="catalog.html"', self.sidebar)
        self.assertIn('href="observability.html#alerts"', self.sidebar)
        self.assertIn('href="operations.html#backups"', self.sidebar)

    def test_servers_uses_runtime_and_agent_apis(self):
        self.assertIn("/api/runtime/list", self.servers_js)
        self.assertIn("/api/runtime?", self.servers_js)
        self.assertIn("/api/agents", self.servers_js)
        self.assertIn("48", self.servers_js)
        self.assertIn("Visão Geral das Instâncias", self.servers_html)
        composition = (ROOT / "dashboard/server_part14.py").read_text(encoding="utf-8")
        for route in ("/servers.html", "/servers.js", "/servers.css"):
            self.assertIn(route, composition)
        compatibility = (ROOT / "dashboard/web/servers-v2.html").read_text(encoding="utf-8")
        self.assertIn("servers.html", compatibility)
        self.assertIn('id="log-agent"', (ROOT / "dashboard/web/observability.html").read_text(encoding="utf-8"))
        self.assertIn('metadata["recent_logs"]', (ROOT / "dashboard/agent_heartbeat_api.py").read_text(encoding="utf-8"))

    def test_infrastructure_v2_keeps_installation_and_topology_views(self):
        for view in ('data-infra-view="agents"','data-infra-view="topology"','data-infra-view="installation"'):
            self.assertIn(view, self.infrastructure_ui)
        self.assertIn("/infrastructure?active_only=true", self.infrastructure_ui)
        self.assertIn("add-agent", self.infrastructure_ui)

    def test_topology_v2_consumes_real_topology_and_marks_placement_estimate(self):
        for value in ("/infrastructure?active_only=true","placement_ready","Agents sem localização","placement_ready estimado","Gerenciar Agent","agent_location"):
            self.assertIn(value, self.topology)

    def test_remote_ssh_installation_remains_available_after_redesign(self):
        for value in ('value="ssh"','id="agent-ssh-host"','id="agent-ssh-user"','id="agent-ssh-port"',"O Dashboard não aceita senha SSH"):
            self.assertIn(value, self.html)

    def test_agent_terminal_stylesheet_is_registered_and_loaded(self):
        html = (ROOT / "dashboard/web/agents.html").read_text(encoding="utf-8")
        server = (ROOT / "dashboard/server_part13.py").read_text(encoding="utf-8")
        css = (ROOT / "dashboard/web/agent-terminal.css").read_text(encoding="utf-8")
        self.assertIn('href="/agent-terminal.css"', html)
        self.assertIn('legacy.STATIC_FILES["/agent-terminal.css"]', server)
        self.assertIn(".agent-terminal-line", css)
        self.assertIn("display: block", css)


if __name__ == "__main__":
    unittest.main()
