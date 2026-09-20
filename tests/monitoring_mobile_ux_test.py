#!/usr/bin/env python3
"""Responsive and human-readable Monitoring UI contract tests."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class MonitoringMobileUXTest(unittest.TestCase):
    def test_monitoring_page_has_mobile_controls_and_cache_bust(self):
        page = (WEB / "monitoring.html").read_text(encoding="utf-8")
        self.assertIn('class="cap-home cap-observability-shell cap-monitoring-view"', page)
        self.assertIn('id="observability-metric-filter"', page)
        self.assertIn('id="monitoring-summary"', page)
        self.assertIn('/observability.js?v=6', page)

    def test_metrics_are_grouped_and_humanized(self):
        script = (WEB / "observability.js").read_text(encoding="utf-8")
        self.assertIn('"host.memory.usage_pct":"Uso de memória"', script)
        self.assertIn('"host.disk.usage_pct":"Uso do disco"', script)
        self.assertIn('"host.network.rx_bytes":"Dados recebidos"', script)
        self.assertIn('function metricGroup(raw)', script)
        self.assertIn('function humanMetricName(raw)', script)
        self.assertIn('function renderMonitoringMetrics(rows)', script)
        self.assertIn('observability-metric-filter', script)

    def test_mobile_layout_is_scannable(self):
        css = (WEB / "observability.css").read_text(encoding="utf-8")
        self.assertIn(".cap-monitoring-grid", css)
        self.assertIn("@media(max-width:640px)", css)
        self.assertIn("@media(max-width:390px)", css)
        self.assertIn("grid-template-columns:1fr 1fr", css)
        self.assertIn(".cap-monitoring-metric-name", css)


if __name__ == "__main__":
    unittest.main()
