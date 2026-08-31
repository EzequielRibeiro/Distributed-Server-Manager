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
        perf = {
            "read_bytes_per_second": 4096.0,
            "write_bytes_per_second": 2048.0,
            "read_iops": 12.0,
            "write_iops": 7.0,
            "processor_queue_length": 2.0,
        }
        disk = {
            "total_bytes": 100_000,
            "used_bytes": 40_000,
            "free_bytes": 60_000,
            "usage_pct": 40.0,
            "read_bytes_per_second": 4096.0,
            "write_bytes_per_second": 2048.0,
            "read_iops": 12.0,
            "write_iops": 7.0,
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
            patch.object(host_telemetry, "_performance_snapshot", return_value=perf),
            patch.object(host_telemetry, "_cpu_usage_pct", return_value=12.5),
            patch.object(host_telemetry, "_memory", return_value=memory),
            patch.object(host_telemetry, "_disk", return_value=disk),
            patch.object(host_telemetry, "_uptime_seconds", return_value=321.0),
            patch.object(host_telemetry, "_network", return_value=network),
            patch.object(host_telemetry, "_temperature_c", return_value=52.3),
            patch.object(host_telemetry, "_agent_process", return_value=agent),
        ):
            result = host_telemetry.collect_host_telemetry()

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["host"]["cpu_usage_pct"], 12.5)
        self.assertEqual(result["host"]["memory"], memory)
        self.assertEqual(result["host"]["disk"], disk)
        self.assertEqual(result["host"]["network"], network)
        self.assertEqual(result["host"]["uptime_seconds"], 321.0)
        self.assertEqual(result["host"]["temperature_c"], 52.3)
        self.assertEqual(result["host"]["processor_queue_length"], 2.0)
        self.assertEqual(
            result["host"]["load_average"],
            {"1m": None, "5m": None, "15m": None},
        )
        self.assertEqual(result["agent"], agent)
        self.assertEqual(result["top_processes"], [])

    def test_disk_activity_derives_rates_from_raw_counter_deltas(self):
        host_telemetry._previous_disk = None
        with (
            patch.object(
                host_telemetry,
                "_disk_raw_totals",
                side_effect=[(1000, 2000, 10, 20), (5000, 8000, 30, 50)],
            ),
            patch.object(host_telemetry.time, "monotonic", side_effect=[10.0, 12.0]),
        ):
            first = host_telemetry._disk_activity()
            second = host_telemetry._disk_activity()

        self.assertIsNone(first["read_bytes_per_second"])
        self.assertIsNone(first["write_bytes_per_second"])
        self.assertEqual(second["read_bytes_per_second"], 2000.0)
        self.assertEqual(second["write_bytes_per_second"], 3000.0)
        self.assertEqual(second["read_iops"], 10.0)
        self.assertEqual(second["write_iops"], 15.0)

    def test_windows_perf_sources_cover_disk_io_queue_and_temperature(self):
        source = (WINDOWS_RUNTIME / "host_telemetry.py").read_text(encoding="utf-8")
        self.assertIn("Win32_PerfRawData_PerfDisk_PhysicalDisk", source)
        self.assertIn("DiskReadBytesPersec", source)
        self.assertIn("DiskWriteBytesPersec", source)
        self.assertIn("DiskReadsPersec", source)
        self.assertIn("DiskWritesPersec", source)
        self.assertIn("ProcessorQueueLength", source)
        self.assertIn("MSAcpi_ThermalZoneTemperature", source)

    def test_runtime_metrics_publishes_host_telemetry_and_windows_queue(self):
        source = (WINDOWS_RUNTIME / "runtime_metrics.py").read_text(encoding="utf-8")
        self.assertIn("from host_telemetry import collect_host_telemetry", source)
        self.assertIn("telemetry = collect_host_telemetry()", source)
        self.assertIn('payload["telemetry"] = telemetry', source)
        self.assertIn("capivara.host.processor.queue_length", source)
        self.assertIn('"platform": "windows"', source)

    def test_windows_package_includes_host_telemetry(self):
        builder = (ROOT / "release" / "build_windows_agent_package.py").read_text(encoding="utf-8")
        self.assertIn('if source.endswith(".py")', builder)
        self.assertTrue((WINDOWS_RUNTIME / "host_telemetry.py").is_file())


if __name__ == "__main__":
    unittest.main()
