#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_RUNTIME = ROOT / "agents" / "windows" / "runtime"
if str(WINDOWS_RUNTIME) not in sys.path:
    sys.path.insert(0, str(WINDOWS_RUNTIME))

import host_telemetry


class WindowsHostTelemetryTest(unittest.TestCase):
    def test_collect_host_telemetry_matches_controller_contract(self):
        memory = {
            "total_bytes": 8_000,
            "used_bytes": 3_000,
            "available_bytes": 5_000,
            "usage_pct": 37.5,
        }
        disk = {
            "total_bytes": 100_000,
            "used_bytes": 40_000,
            "free_bytes": 60_000,
            "usage_pct": 40.0,
            "read_bytes_per_second": None,
            "write_bytes_per_second": None,
            "read_iops": None,
            "write_iops": None,
        }
        network = {
            "rx_bytes": 123,
            "tx_bytes": 456,
            "rx_bytes_per_second": 12.0,
            "tx_bytes_per_second": 34.0,
        }
        agent = {
            "pid": 99,
            "cpu_usage_pct": 1.5,
            "memory_rss_bytes": 2048,
            "threads": 4,
        }
        with (
            patch.object(host_telemetry, "_cpu_usage_pct", return_value=12.5),
            patch.object(host_telemetry, "_memory", return_value=memory),
            patch.object(host_telemetry, "_disk", return_value=disk),
            patch.object(host_telemetry, "_uptime_seconds", return_value=321.0),
            patch.object(host_telemetry, "_network", return_value=network),
            patch.object(host_telemetry, "_agent_process", return_value=agent),
        ):
            result = host_telemetry.collect_host_telemetry()

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["host"]["cpu_usage_pct"], 12.5)
        self.assertEqual(result["host"]["memory"], memory)
        self.assertEqual(result["host"]["disk"], disk)
        self.assertEqual(result["host"]["network"], network)
        self.assertEqual(result["host"]["uptime_seconds"], 321.0)
        self.assertEqual(result["agent"], agent)
        self.assertEqual(result["top_processes"], [])

    def test_runtime_metrics_publishes_host_telemetry(self):
        source = (WINDOWS_RUNTIME / "runtime_metrics.py").read_text(encoding="utf-8")
        self.assertIn("from host_telemetry import collect_host_telemetry", source)
        self.assertIn("telemetry = collect_host_telemetry()", source)
        self.assertIn('payload["telemetry"] = telemetry', source)

    def test_windows_package_includes_host_telemetry(self):
        builder = (ROOT / "release" / "build_windows_agent_package.py").read_text(encoding="utf-8")
        self.assertIn('if source.endswith(".py")', builder)
        self.assertTrue((WINDOWS_RUNTIME / "host_telemetry.py").is_file())


if __name__ == "__main__":
    unittest.main()
