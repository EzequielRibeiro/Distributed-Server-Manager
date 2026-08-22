#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentDashboardTelemetryUiTest(unittest.TestCase):
    def test_dashboard_binds_telemetry_payload_to_metric_cards(self):
        script = (ROOT / "dashboard" / "web" / "agent-updates.js").read_text(encoding="utf-8")
        for token in (
            'cpu_usage_pct',
            'memory_rss_bytes',
            'rx_bytes_per_second',
            'tx_bytes_per_second',
            'temperature_c',
            'top_processes',
            'agent-host-cpu-chart',
            'agent-host-memory-chart',
            'agent-host-disk-chart',
            'agent-process-cpu-chart',
            'agent-process-memory-chart',
            'setInterval',
            '30000',
        ):
            self.assertIn(token, script)

    def test_dashboard_uses_text_content_for_process_rows(self):
        script = (ROOT / "dashboard" / "web" / "agent-updates.js").read_text(encoding="utf-8")
        self.assertIn('cell.textContent = String(value)', script)


if __name__ == "__main__":
    unittest.main()
