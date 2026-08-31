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
    def test_top_processes_returns_normalized_rows(self):
        payload = [
            {
                "name": "python",
                "pid": 42,
                "cpu_usage_pct": 12.345,
                "memory_rss_bytes": 123456,
                "threads": 7,
            }
        ]
        with patch.object(process_telemetry, "_run_powershell_json", return_value=payload):
            rows = process_telemetry.collect_top_processes(5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "python")
        self.assertEqual(rows[0]["pid"], 42)
        self.assertEqual(rows[0]["cpu_usage_pct"], 12.35)
        self.assertEqual(rows[0]["memory_rss_bytes"], 123456)
        self.assertEqual(rows[0]["threads"], 7)

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


if __name__ == "__main__":
    unittest.main()
