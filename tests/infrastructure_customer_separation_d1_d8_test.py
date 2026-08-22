#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "dashboard", ROOT / "database", ROOT / "core"):
    sys.path.insert(0, str(directory))

from agent_heartbeat_api import _observability_from_heartbeat


class InfrastructureCustomerSeparationD1D8Test(unittest.TestCase):
    def source(self, path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_d1_admin_home_has_no_instance_lifecycle_controls(self):
        page = self.source("dashboard/web/index.html")
        script = self.source("dashboard/web/app.js")
        for token in ("btn-start", "btn-stop", "btn-restart", "catalog-v2-instance-reinstall", "catalog-v2-config-editor"):
            self.assertNotIn(token, page)
        self.assertNotIn("/api/instance/", script)
        self.assertIn("/api/admin/infrastructure/overview", script)

    def test_d2_to_d4_admin_home_is_infrastructure_telemetry(self):
        page = self.source("dashboard/web/index.html")
        for token in ("Telemetria geral do Controller", "Agents", "Dashboard CPU", "Dashboard RAM"):
            self.assertIn(token, page)
        service = self.source("dashboard/admin_infrastructure_service.py")
        self.assertIn("controller_telemetry", service)
        self.assertIn("host.cpu.percent", service)
        self.assertIn("agent.cpu.percent", service)

    def test_d3_to_d6_heartbeat_maps_host_agent_and_instance_metrics(self):
        body = {
            "host_telemetry": {
                "collected_at": "2026-08-22T13:00:00Z",
                "cpu_percent": 21.5,
                "memory": {"used_percent": 30.0, "used_bytes": 300, "available_bytes": 700},
                "storage": {"used_percent": 40.0, "free_bytes": 600},
                "load": {"load1": 0.5, "load5": 0.4, "load15": 0.3},
                "uptime_seconds": 1000,
                "network": {"rx_bytes": 123, "tx_bytes": 456},
            },
            "agent_telemetry": {"collected_at": "2026-08-22T13:00:00Z", "pid": 42, "cpu_percent": 1.25, "rss_bytes": 2048, "threads": 3},
            "instance_resource_metrics": [{"instance_id": "i1", "game_id": "dayz", "cpu_percent": 5.5, "memory_bytes": 4096, "pid": 99, "tasks": 6, "io_read_bytes": 1, "io_write_bytes": 2, "collected_at": "2026-08-22T13:00:00Z"}],
        }
        samples = _observability_from_heartbeat("agent-1", body)
        names = {(item["scope_type"], item.get("instance_id"), item["metric_name"]) for item in samples}
        self.assertIn(("agent", None, "host.cpu.percent"), names)
        self.assertIn(("agent", None, "agent.memory.rss.bytes"), names)
        self.assertIn(("instance", "i1", "instance.cpu.percent"), names)
        self.assertIn(("instance", "i1", "instance.io.write.bytes"), names)

    def test_d5_agent_page_is_diagnostic_and_node_game_data_only(self):
        page = self.source("dashboard/web/agents.html")
        script = self.source("dashboard/web/agents.js")
        for token in ("Telemetria do computador", "Telemetria do Capivara Agent", "Instâncias hospedadas", "Instalar jogo no Agent"):
            self.assertIn(token, page)
        self.assertIn("/agents/game-data", script)
        for path in ("/instance/start", "/instance/stop", "/instance/restart", "/instance/reinstall"):
            self.assertNotIn(path, script)

    def test_d6_linux_and_windows_agents_publish_same_resource_contract(self):
        for path in ("agents/linux/runtime/agent.py", "agents/windows/runtime/agent.py"):
            source = self.source(path)
            self.assertIn('"host_telemetry"', source)
            self.assertIn('"agent_telemetry"', source)
            self.assertIn('"instance_resource_metrics"', source)
            self.assertIn("collect_instance_resources", source)

    def test_d7_customer_admin_owns_instance_operations(self):
        page = self.source("dashboard/web/customer-admin.html")
        script = self.source("dashboard/web/customer-admin.js")
        for label in ("Start", "Stop", "Restart", "Reinstalar", "Logs", "Configuração", "Arquivos", "Conteúdo / Mods", "Backups", "Eventos"):
            self.assertIn(label, page)
        self.assertIn('/api/instance/${action}', script)
        for path in ("/api/instance/reinstall/v2", "/api/instance/logs", "/api/instance/backups"):
            self.assertIn(path, script)
        self.assertIn("/api/catalog/install", script)
        self.assertIn("/api/instance/file/text", script)
        self.assertIn('lifecycle("start")', script)
        self.assertIn('lifecycle("stop")', script)
        self.assertIn('lifecycle("restart")', script)

    def test_d8_server_composition_remains_modular(self):
        api = self.source("dashboard/customer_admin_api.py")
        self.assertIn("AdminInfrastructureService", api)
        self.assertIn("/api/admin/infrastructure/overview", api)
        self.assertIn("/api/admin/agent/detail", api)
        server = self.source("dashboard/server.py")
        self.assertNotIn("AdminInfrastructureService", server)


if __name__ == "__main__":
    unittest.main()
