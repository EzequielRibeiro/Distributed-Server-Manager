#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentDashboardNodeMetricsContractTest(unittest.TestCase):

    def test_controller_persists_extended_agent_metrics(self):
        source = (
            ROOT / "dashboard/agent_heartbeat_api.py"
        ).read_text(encoding="utf-8")

        expected = (
            "capivara.host.disk.read_bytes_per_second",
            "capivara.host.disk.write_bytes_per_second",
            "capivara.host.disk.read_iops",
            "capivara.host.disk.write_iops",
            "capivara.agent.players.online",
            "capivara.agent.players.capacity",
            "capivara.agent.instances.running",
            "capivara.agent.instances.total",
            "capivara.agent.instances.storage_used_bytes",
        )

        for metric in expected:
            self.assertIn(metric, source)


    def test_linux_agent_collects_disk_io(self):
        source = (
            ROOT / "agents/linux/runtime/host_telemetry.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"/proc"', source)
        self.assertIn('"diskstats"', source)
        self.assertIn('"read_bytes_per_second"', source)
        self.assertIn('"write_bytes_per_second"', source)
        self.assertIn('"read_iops"', source)
        self.assertIn('"write_iops"', source)


if __name__ == "__main__":
    unittest.main()
