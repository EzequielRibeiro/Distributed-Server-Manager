from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import agent_port_preflight


class AgentPortPreflightTest(unittest.TestCase):
    def summary(self, *, contiguous=10, conflicts=0, complete=True):
        return {
            "agent": {"network": {"complete": complete}},
            "ranges": [{
                "protocol": "tcp",
                "start_port": 24000,
                "end_port": 24099,
                "largest_contiguous_available": contiguous,
            }],
            "conflict_count": conflicts,
            "observed_conflict_count": conflicts,
        }

    def test_ready_when_contiguous_capacity_exists(self):
        with mock.patch.object(agent_port_preflight, "effective_port_summary", return_value=self.summary()):
            result = agent_port_preflight.port_pool_preflight(object(), "agent-1", protocol="tcp", required_contiguous=4)
        self.assertTrue(result["ready"])
        self.assertEqual(result["eligible_range_count"], 1)
        self.assertEqual(result["reasons"], [])

    def test_reports_capacity_conflict_and_incomplete_inventory(self):
        with mock.patch.object(
            agent_port_preflight,
            "effective_port_summary",
            return_value=self.summary(contiguous=2, conflicts=1, complete=False),
        ):
            result = agent_port_preflight.port_pool_preflight(object(), "agent-1", protocol="tcp", required_contiguous=4)
        self.assertFalse(result["ready"])
        self.assertIn("insufficient_contiguous_capacity", result["reasons"])
        self.assertIn("unmanaged_os_socket_overlap", result["reasons"])
        self.assertIn("network_inventory_incomplete", result["reasons"])

    def test_protocol_validation_is_fail_closed(self):
        with self.assertRaises(ValueError):
            agent_port_preflight.port_pool_preflight(object(), "agent-1", protocol="sctp")


if __name__ == "__main__":
    unittest.main()
