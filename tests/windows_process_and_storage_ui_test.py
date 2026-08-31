#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "windows" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import process_telemetry


class WindowsProcessAndStorageUiTest(unittest.TestCase):
    def setUp(self):
        process_telemetry._previous_processes = {}

    def test_top_processes_uses_raw_cpu_delta(self):
        first = [
            {
                "name": "python",
                "pid": 42,
                "cpu_raw": 1_000,
                "timestamp_sys100ns": 10_000,
                "memory_rss_bytes": 123456,
                "threads": 7,
            },
            {
                "name": "worker",
                "pid": 43,
                "cpu_raw": 2_000,
                "timestamp_sys100ns": 10_000,
                "memory_rss_bytes": 234567,
                "threads": 4,
            },
        ]
        second = [
            {
                "name": "python",
                "pid": 42,
                "cpu_raw": 2_000,
                "timestamp_sys100ns": 20_000,
                "memory_rss_bytes": 123456,
                "threads": 7,
            },
            {
                "name": "worker",
                "pid": 43,
                "cpu_raw": 2_500,
                "timestamp_sys100ns": 20_000,
                "memory_rss_bytes": 234567,
                "threads": 4,
            },
        ]
        with patch.object(process_telemetry, "_raw_processes", side_effect=[first, second]), patch.object(
            process_telemetry.os, "cpu_count", return_value=1
        ):
            initial = process_telemetry.collect_top_processes(5)
            rows = process_telemetry.collect_top_processes(5)

        self.assertEqual(initial[0]["cpu_usage_pct"], None)
        self.assertEqual(rows[0]["name"], "python")
        self.assertEqual(rows[0]["pid"], 42)
        self.assertEqual(rows[0]["cpu_usage_pct"], 10.0)
        self.assertEqual(rows[0]["memory_rss_bytes"], 123456)
        self.assertEqual(rows[0]["threads"], 7)
        self.assertEqual(rows[1]["cpu_usage_pct"], 5.0)

    def test_runtime_metrics_publishes_top_five(self):
        source = (RUNTIME / "runtime_metrics.py").read_text(encoding="utf-8")
        self.assertIn("from process_telemetry import collect_top_processes", source)
        self.assertIn('telemetry["top_processes"] = collect_top_processes(5)', source)

    def test_storage_pool_ui_has_no_undefined_auth_gate(self):
        source = (ROOT / "dashboard" / "web" / "agent-storage-pools.js").read_text(encoding="utf-8")
        self.assertNotIn("!auth()", source)
        self.assertIn("if(!agentId)return", source)
        self.assertIn('credentials:"same-origin"', source)
        self.assertIn("/api/admin/agent/storage-pools", source)

    def test_legacy_storage_pools_skip_admin_read(self):
        source = (ROOT / "dashboard" / "web" / "agent-storage-pools.js").read_text(encoding="utf-8")
        self.assertIn("const legacyOnly=pools.length>0&&pools.every", source)
        self.assertIn("if(legacyOnly){renderObserved(pools);return;}", source)
        self.assertLess(
            source.index("/api/agent/ports?agent_id="),
            source.index("/api/admin/agent/storage-pools?agent_id="),
        )


if __name__ == "__main__":
    unittest.main()
