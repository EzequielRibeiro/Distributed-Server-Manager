#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentDashboardUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web = ROOT / "dashboard/web"
        cls.html = (web / "agents.html").read_text(encoding="utf-8")
        cls.agent_script = (web / "agents.js").read_text(encoding="utf-8")
        cls.install = (web / "agent-installation.js").read_text(encoding="utf-8")
        cls.location = (web / "agent-location-ui.js").read_text(encoding="utf-8")
        cls.updates = (web / "agent-updates.js").read_text(encoding="utf-8")
        cls.sidebar = (web / "components/sidebar.html").read_text(encoding="utf-8")
        cls.servers_html = (web / "servers-v2.html").read_text(encoding="utf-8")
        cls.servers_js = (web / "servers-v2.js").read_text(encoding="utf-8")
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

    def test_location_controls_include_region_and_instance_safety_boundary(self):
        self.assertIn('id="agent-region"', self.html)
        self.assertIn('id="agent-datacenter"', self.html)
        self.assertIn('id="agent-public-host"', self.html)
        self.assertIn('id="agent-latitude"', self.html)
        self.assertIn('id="agent-longitude"', self.html)
        self.assertIn("Start, Stop, Restart, reinstalação, arquivos e backups são administrados em Clientes", self.html)
        self.assertIn("region_id", self.location)

    def test_remote_update_controls_and_batch_contract_are_present(self):
        for text in ("Versão instalada", "Versão disponível", "Tamanho do lote", "Stable", "Beta", "Local / manual"):
            self.assertIn(text, self.html)
        self.assertIn("/agents/updates/rollouts", self.updates)
        self.assertIn("/agents/updates/status", self.updates)
        self.assertIn("batch_size", self.updates)

    def test_phase_assets_and_current_entrypoint_are_loaded(self):
        self.assertIn('/agent-installation.js', self.html)
        self.assertIn('/agent-location-ui.js', self.html)
        self.assertIn('/agent-updates.js', self.html)
        self.assertIn('/infrastructure-ui-v2.js', self.html)
        self.assertIn('/infrastructure-topology-v2.js', self.html)
        self.assertIn('dashboard/server_part14.py', self.service)

    def test_admin_navigation_is_infrastructure_and_operations_oriented(self):
        self.assertIn('href="agents.html"', self.sidebar)
        self.assertIn('href="operations.html"', self.sidebar)
        self.assertIn('operations.html#incidents', self.sidebar)
        self.assertIn('operations.html#alerts', self.sidebar)
        self.assertIn('operations.html#events', self.sidebar)
        self.assertIn('operations.html#schedules', self.sidebar)
        self.assertIn('operations.html#logs', self.sidebar)
        self.assertIn('operations.html#controller-backup', self.sidebar)
        self.assertIn('class="admin-only"', self.sidebar)
        self.assertIn('agent-manager-only', self.sidebar)
        self.assertNotIn('index.html#backup-total', self.sidebar)
        self.assertNotIn('index.html#scheduler-list', self.sidebar)
        self.assertIn('dashboard-ui-v2.css', self.sidebar)
        self.assertIn('dashboard-ui-v2-stage2.css', self.sidebar)

    def test_servers_v2_uses_runtime_and_agent_apis(self):
        self.assertIn("/api/runtime/list", self.servers_js)
        self.assertIn("/api/runtime?", self.servers_js)
        self.assertIn("/api/agents", self.servers_js)
        self.assertIn("48", self.servers_js)
        self.assertIn("Visão Geral das Instâncias", self.servers_html)
        server = (ROOT / "dashboard/server.py").read_text(encoding="utf-8")
        for route in ("/servers-v2.html", "/servers-v2.js", "/servers-v2.css"):
            self.assertIn(route, server)
        self.assertIn('id="agent-recent-logs"', self.html)
        self.assertIn('metadata["recent_logs"]', (ROOT / "dashboard/agent_heartbeat_api.py").read_text(encoding="utf-8"))

    def test_agent_detail_exposes_host_agent_and_instance_telemetry(self):
        for token in ('id="agent-host-telemetry"', 'id="agent-process-telemetry"', 'id="agent-instance-resources"', 'id="agent-game-data-panel"'):
            self.assertIn(token, self.html)
        self.assertIn('/admin/agent/detail?agent_id=', self.agent_script)
        self.assertIn('/agents/game-data', self.agent_script)
        self.assertNotIn('/instance/start', self.agent_script)
        self.assertNotIn('/instance/stop', self.agent_script)

    def test_infrastructure_v2_keeps_installation_and_topology_views(self):
        for view in ('data-infra-view="agents"', 'data-infra-view="topology"', 'data-infra-view="installation"'):
            self.assertIn(view, self.infrastructure_ui)
        self.assertIn("/infrastructure?active_only=true", self.infrastructure_ui)
        self.assertIn("add-agent", self.infrastructure_ui)

    def test_topology_v2_consumes_real_topology_and_marks_placement_estimate(self):
        self.assertIn("/infrastructure?active_only=true", self.topology)
        self.assertIn("placement_ready", self.topology)
        self.assertIn("Agents sem localização", self.topology)
        self.assertIn("placement_ready estimado", self.topology)
        self.assertIn("Gerenciar Agent", self.topology)
        self.assertIn("agent_location", self.topology)

    def test_remote_ssh_installation_remains_available_after_redesign(self):
        self.assertIn('value="ssh"', self.html)
        self.assertIn('id="agent-ssh-host"', self.html)
        self.assertIn('id="agent-ssh-user"', self.html)
        self.assertIn('id="agent-ssh-port"', self.html)
        self.assertIn("Controller não armazena senha SSH", self.html)
        self.assertIn("chave/ssh-agent e host key", self.html)


if __name__ == "__main__":
    unittest.main()
