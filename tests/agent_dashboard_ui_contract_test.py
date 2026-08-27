#!/usr/bin/env python3
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class AgentDashboardUiContractTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  web=ROOT/"dashboard/web";cls.html=(web/"agents.html").read_text();cls.add_agent=(web/"add-agent.html").read_text();cls.add_agent_linux=(web/"add-agent-linux.html").read_text() if (web/"add-agent-linux.html").exists() else cls.add_agent;cls.add_agent_windows=(web/"add-agent-windows.html").read_text() if (web/"add-agent-windows.html").exists() else cls.add_agent;cls.detail=(web/"agent-details.html").read_text();cls.fleet_js=(web/"agents-v3.js").read_text();cls.detail_js=(web/"agent-details.js").read_text();cls.install=(web/"agent-installation.js").read_text();cls.sidebar=(web/"components/sidebar-v3.html").read_text();cls.servers_html=(web/"servers.html").read_text();cls.servers_js=(web/"servers.js").read_text();cls.servers_css=(web/"servers.css").read_text();cls.home=(web/"dashboard-v3.html").read_text();cls.home_js=(web/"dashboard-home-v3.js").read_text();cls.telemetry_js=(web/"telemetry-widgets.js").read_text();cls.service=(ROOT/"systemd/dsm-dashboard.service").read_text();cls.composition=(ROOT/"dashboard/server_part14.py").read_text();cls.resource_composition=(ROOT/"dashboard/server_part15.py").read_text();cls.file_composition=(ROOT/"dashboard/server_part16.py").read_text();cls.latest_composition=(ROOT/"dashboard/server_part17.py").read_text()
 def test_agents_page_is_fleet_only_and_uses_v3_shell(self):
  for text in ("dashboard-home-v3.css","agents-v3.css","agents-v3.js","Frota de Agents",'href="add-agent.html"'):self.assertIn(text,self.html)
  for text in ("SteamCMD funcionando","SteamCMD não instalado","data-install-steamcmd","install-steamcmd"):self.assertIn(text,self.fleet_js)
  self.assertNotIn('id="agent-install-form"',self.html);self.assertNotIn('id="agent-detail"',self.html)
 def test_add_agent_controls_live_on_dedicated_page(self):
  self.assertIn("Adicionar Agent",self.add_agent);self.assertIn("Linux",self.add_agent);self.assertIn("Windows",self.add_agent)
  combined=self.add_agent_linux+"\n"+self.add_agent_windows
  for text in ("GitHub Release","Pacote local","Região","Datacenter","Gerar instalação","Aguardando Agent","Pareando","Validando","Online"):self.assertIn(text,combined)
  for value in ('value="ssh"','id="agent-ssh-host"','id="agent-ssh-user"','id="agent-ssh-port"'):self.assertIn(value,combined)
  self.assertTrue("O Dashboard não aceita senha SSH" in combined or "arquivo de senha protegido" in combined.lower())
  self.assertIn("/agents/installations",self.install);self.assertIn("/agents/installations/status",self.install)
 def test_agent_details_are_separate_from_fleet(self):
  for text in ("Detalhes do Agent","Portas administradas","Localização e Placement","Monitoramento",'id="agent-telemetry"',"telemetry-widgets.js"):self.assertIn(text,self.detail)
  for text in ("/api/agent/ports","/api/observability?mode=history","CapivaraTelemetry"):self.assertIn(text,self.detail_js)
  self.assertIn("agent-details.html?agent_id=",self.fleet_js)
 def test_controller_telemetry_is_on_dashboard_home(self):
  self.assertIn('id="controller-telemetry"',self.home);self.assertIn("telemetry-widgets.js",self.home);self.assertIn("/controller/telemetry?window_seconds=3600",self.home_js);self.assertIn("/api/controller/telemetry",self.latest_composition);self.assertIn("telemetry-widgets.css",self.latest_composition)
 def test_dashboard_v3_navigation_preserves_rbac_and_add_agent(self):
  for text in ('href="servers.html"','href="agents.html"','href="add-agent.html"','admin-only','agent-manager-only','href="catalog.html"','href="game-profiles.html"','href="observability.html#alerts"','href="operations.html#backups"'):self.assertIn(text,self.sidebar)
  self.assertNotIn("Criar instância",self.sidebar)
 def test_agent_v3_routes_are_registered_in_composition_layer(self):
  for route in ("/agents.html","/agents-v3.js","/agents-v3.css","/agent-steam-status.css","/add-agent.html","/add-agent-v3.css","/agent-details.html","/agent-details.js","/agent-details.css","/catalog-installation.css"):self.assertIn(route,self.composition)
  self.assertIn('dashboard/server_part17.py',self.service);self.assertIn('import server_part14 as integration',self.resource_composition);self.assertIn('import server_part15 as integration',self.file_composition);self.assertIn('import server_part16 as integration',self.latest_composition)
 def test_servers_uses_runtime_and_agent_apis(self):
  for text in ("/api/runtime/list","/api/runtime?","/api/agents","48"):self.assertIn(text,self.servers_js)
  self.assertIn("Visão Geral das Instâncias",self.servers_html)
  for text in ("--cap-bg:#0b111b","background:var(--cap-bg)!important","color-scheme:dark"):self.assertIn(text,self.servers_css)
  self.assertIn('window.innerWidth<=760',self.servers_js);self.assertIn('classList.toggle("sidebar-open")',self.servers_js);self.assertNotIn("cap-sidebar-open",self.servers_js)
  for route in ("/servers.html","/servers.js","/servers.css"):self.assertIn(route,self.composition)
  self.assertIn("servers.html",(ROOT/"dashboard/web/servers-v2.html").read_text());self.assertIn('id="log-agent"',(ROOT/"dashboard/web/observability.html").read_text());self.assertIn('metadata["recent_logs"]',(ROOT/"dashboard/agent_heartbeat_api.py").read_text())
if __name__=="__main__":unittest.main()
