#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"
sys.path.insert(0, str(DASHBOARD))
sys.path.insert(0, str(DATABASE))

from agent_heartbeat_api import _observability_from_heartbeat, _telemetry_from_heartbeat


class AgentHeartbeatTelemetryContractTest(unittest.TestCase):
    def test_runtime_metrics_telemetry_is_discovered(self):
        telemetry = {
            "schema_version": 1,
            "host": {
                "cpu_usage_pct": 12.5,
                "memory": {"usage_pct": 33.0},
                "disk": {"usage_pct": 44.0},
                "network": {"rx_bytes_per_second": 1000.0, "tx_bytes_per_second": 500.0},
                "temperature_c": 51.0,
            },
            "agent": {"cpu_usage_pct": 1.5, "memory_rss_bytes": 123456, "threads": 4},
            "top_processes": [],
        }
        body = {"instance_runtime_metrics": {"telemetry": telemetry}}
        self.assertEqual(_telemetry_from_heartbeat(body), telemetry)

        samples = _observability_from_heartbeat("agent-01", body)
        names = {item["metric_name"] for item in samples}
        for expected in (
            "capivara.host.cpu.usage_pct",
            "capivara.host.memory.usage_pct",
            "capivara.host.disk.usage_pct",
            "capivara.host.network.rx_bytes_per_second",
            "capivara.host.network.tx_bytes_per_second",
            "capivara.host.temperature_c",
            "capivara.agent.cpu.usage_pct",
            "capivara.agent.memory.rss_bytes",
            "capivara.agent.threads",
        ):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
