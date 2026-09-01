#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "windows" / "runtime"


class WindowsAgentHostTelemetryContractTest(unittest.TestCase):
    def test_collector_exists_and_matches_controller_contract(self):
        source = (RUNTIME / "host_telemetry.py").read_text(encoding="utf-8")
        for token in (
            '"host"',
            '"cpu_usage_pct"',
            '"memory"',
            '"disk"',
            '"network"',
            '"uptime_seconds"',
            '"agent"',
            '"top_processes"',
            '"rx_bytes_per_second"',
            '"tx_bytes_per_second"',
            '"memory_rss_bytes"',
        ):
            self.assertIn(token, source)

    def test_entrypoint_publishes_telemetry_and_recent_logs(self):
        source = (RUNTIME / "agent_entrypoint.py").read_text(encoding="utf-8")
        self.assertIn("from host_telemetry import collect_host_telemetry", source)
        self.assertIn('payload["telemetry"] = collect_host_telemetry()', source)
        self.assertIn('payload["agent_logs"] = _recent_logs()', source)
        self.assertIn('RUNTIME_LOG = STATE_DIR / "agent-runtime.log"', source)
        self.assertIn('heartbeat ok ', source)
        self.assertIn('heartbeat failed:', source)

    def test_windows_package_builder_is_recursive_for_runtime_python(self):
        builder = (ROOT / "release" / "build_windows_agent_package.py").read_text(encoding="utf-8")
        # git ls-tree -r walks the full runtime tree, so newly-added Python
        # modules such as host_telemetry.py are included automatically.
        self.assertIn('git_text("ls-tree","-r","--name-only",ref,"agents/windows/runtime")', builder)
        self.assertIn('if source.endswith(".py")', builder)
        self.assertIn('relative=source.removeprefix("agents/windows/")', builder)


if __name__ == "__main__":
    unittest.main()
