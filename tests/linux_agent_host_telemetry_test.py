#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
sys.path.insert(0, str(RUNTIME))

from host_telemetry import collect_host_telemetry


class LinuxAgentHostTelemetryTest(unittest.TestCase):
    def test_collector_exposes_platform_neutral_contract(self):
        first = collect_host_telemetry()
        second = collect_host_telemetry()

        self.assertEqual(second["schema_version"], 1)
        self.assertIn("host", second)
        self.assertIn("agent", second)
        self.assertIn("top_processes", second)

        host = second["host"]
        for key in ("cpu_usage_pct", "memory", "disk", "load_average", "uptime_seconds", "network", "temperature_c"):
            self.assertIn(key, host)

        memory = host["memory"]
        self.assertGreater(memory["total_bytes"] or 0, 0)
        self.assertGreaterEqual(memory["used_bytes"] or 0, 0)
        self.assertGreaterEqual(memory["available_bytes"] or 0, 0)

        disk = host["disk"]
        self.assertGreater(disk["total_bytes"] or 0, 0)
        self.assertGreaterEqual(disk["used_bytes"] or 0, 0)

        network = host["network"]
        for key in ("rx_bytes", "tx_bytes", "rx_bytes_per_second", "tx_bytes_per_second"):
            self.assertIn(key, network)

        agent = second["agent"]
        self.assertGreater(agent["pid"], 0)
        self.assertIn("cpu_usage_pct", agent)
        self.assertIn("memory_rss_bytes", agent)
        self.assertIn("threads", agent)
        self.assertLessEqual(len(second["top_processes"]), 5)

        # First samples may not have rates; the second sample must remain JSON-safe
        # and should have established previous counters when procfs is available.
        self.assertIsInstance(first["collected_at_unix"], float)
        self.assertIsInstance(second["collected_at_unix"], float)


if __name__ == "__main__":
    unittest.main()
