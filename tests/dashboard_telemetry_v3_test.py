#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DashboardTelemetryV3Test(unittest.TestCase):
    def test_agent_details_restores_telemetry(self):
        html = (ROOT / "dashboard/web/agent-details.html").read_text(encoding="utf-8")
        js = (ROOT / "dashboard/web/agent-details.js").read_text(encoding="utf-8")
        self.assertIn('id="agent-telemetry"', html)
        self.assertIn("telemetry-widgets.js", html)
        self.assertIn("/api/observability?mode=history", js)
        self.assertIn("result.telemetry", js)
        self.assertIn("CapivaraTelemetry", js)

    def test_shared_charts_include_operational_context(self):
        js = (ROOT / "dashboard/web/telemetry-widgets.js").read_text(encoding="utf-8")
        css = (ROOT / "dashboard/web/telemetry-widgets.css").read_text(encoding="utf-8")
        for marker in ("Atual", "Média", "Pico", "sampleTime", "current-point", "Janela:"):
            self.assertIn(marker, js)
        for marker in ("cap-telemetry-stats", "axis-label", "current-point", "cap-telemetry-no-data"):
            self.assertIn(marker, css)
        for page in ("dashboard-v3.html", "agent-details.html"):
            html = (ROOT / "dashboard/web" / page).read_text(encoding="utf-8")
            self.assertIn("telemetry-widgets.css?v=4", html)
            self.assertIn("telemetry-widgets.js?v=4", html)

    def test_controller_telemetry_is_on_home(self):
        html = (ROOT / "dashboard/web/dashboard-v3.html").read_text(encoding="utf-8")
        js = (ROOT / "dashboard/web/dashboard-home-v3.js").read_text(encoding="utf-8")
        composition = (ROOT / "dashboard/server_part17.py").read_text(encoding="utf-8")
        self.assertIn('id="controller-telemetry"', html)
        self.assertIn("/controller/telemetry?window_seconds=3600", js)
        self.assertIn("/api/controller/telemetry", composition)
        self.assertIn("controller_telemetry", composition)
        self.assertIn("telemetry-widgets.css", composition)

    def test_heartbeat_persists_extended_agent_metrics(self):
        source = (ROOT / "dashboard/agent_heartbeat_api.py").read_text(encoding="utf-8")
        for metric in (
            "capivara.host.load.1m",
            "capivara.host.uptime_seconds",
            "capivara.host.memory.used_bytes",
            "capivara.host.disk.total_bytes",
            "capivara.agent.pid",
        ):
            self.assertIn(metric, source)


if __name__ == "__main__":
    unittest.main()
