#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentDashboardUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web = ROOT / "dashboard/web"
        cls.html = (web / "agents.html").read_text(encoding="utf-8")
        cls.add_agent = (web / "add-agent.html").read_text(encoding="utf-8")
        cls.detail = (web / "agent-details.html").read_text(encoding="utf-8")
        cls.fleet_js = (web / "agents-v3.js").read_text(encoding="utf-8")
        cls.detail_js = (web / "agent-details.js").read_text(encoding="utf-8")
        cls.install = (web / "agent-installation.js").read_text(encoding="utf-8")
        cls.sidebar = (web / "components/sidebar-v3.html").read_text(encoding="utf-8")
        cls.servers_html = (web / "servers.html").read_text(encoding="utf-8")
        cls.servers_js = (web / "servers.js").read_text(encoding="utf-8")
        cls.service = (ROOT / "systemd/dsm-dashboard.service").read_text(encoding="utf-8")
        cls.composition = (ROOT / "dashboard/server_part14.py").read_text(encoding="utf-8")

    def test_agents_page_is_fleet_only_and_uses_v3_shell(self):
        self.assertIn("dashboard-home-v3.css", self.html)
        self.assertIn("agents-v3.css", self.html)
        self.assertIn("agents-v3.js", self.html)
        self.assertIn("Frota de Agents", self.html)
        self.assertIn('href="add-agent.html"', self.html)
        self.assertNotIn('id="agent-install-form"', self.html)
        self.assertNotIn('id="agent-detail"', self.html)

    def test_add_agent_controls_live_on_dedicated_page(self):
        for text in ("Adicionar Agent", "Linux", "Windows", "GitHub Release", "Pacote local", "Região", "Datacenter", "Gerar instalação"):
            self.assertIn(text, self.add_agent)
        for text in ("Aguardando Agent", "Pareando", "Validando", "Online"):
            self.assertIn(text, self.add_agent)
        for value in ('value="ssh"', 'id="agent-ssh-host"', 'id="agent-ssh-user"', 'id="agent-ssh-port"', "O Dashboard não aceita senha SSH"):
            self.assertIn(value, self.add_agent)
        self.assertIn("/agents/installations", self.install)
        self.assertIn("/agents/installations/status", self.install)

    def test_agent_details_are_separate_from_fleet(self):
        self.assertIn("Detalhes do Agent", self.detail)
        self.assertIn("Portas administradas", self.detail)
        self.assertIn("Localização e Placement", self.detail)
        self.assertIn("Monitoramento", self.detail)
        self.assertIn("/api/agent/ports", self.detail_js)
        self.assertIn("agent-details.html?agent_id=", self.fleet_js)

    def test_dashboard_v3_navigation_preserves_rbac_and_add_agent(self):
        self.assertIn('href="servers.html"', self.sidebar)
        self.assertIn('href="agents.html"', self.sidebar)
        self.assertIn('href="add-agent.html"', self.sidebar)
        for role_class in ('admin-only', 'agent-manager-only', 'instance-manager-only'):
            self.assertIn(role_class, self.sidebar)
        self.assertIn('href="catalog.html"', self.sidebar)
        self.assertIn('href="observability.html#alerts"', self.sidebar)
        self.assertIn('href="operations.html#backups"', self.sidebar)

    def test_agent_v3_routes_are_registered_in_composition_layer(self):
        for route in (
            "/agents.html", "/agents-v3.js", "/agents-v3.css", "/add-agent.html",
            "/add-agent-v3.css", "/agent-details.html", "/agent-details.js", "/agent-details.css"
        ):
            self.assertIn(route, self.composition)
        self.assertIn('dashboard/server_part14.py', self.service)

    def test_servers_uses_runtime_and_agent_apis(self):
        self.assertIn("/api/runtime/list", self.servers_js)
        self.assertIn("/api/runtime?", self.servers_js)
        self.assertIn("/api/agents", self.servers_js)
        self.assertIn("48", self.servers_js)
        self.assertIn("Visão Geral das Instâncias", self.servers_html)
        for route in ("/servers.html", "/servers.js", "/servers.css"):
            self.assertIn(route, self.composition)
        compatibility = (ROOT / "dashboard/web/servers-v2.html").read_text(encoding="utf-8")
        self.assertIn("servers.html", compatibility)
        self.assertIn('id="log-agent"', (ROOT / "dashboard/web/observability.html").read_text(encoding="utf-8"))
        self.assertIn('metadata["recent_logs"]', (ROOT / "dashboard/agent_heartbeat_api.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
