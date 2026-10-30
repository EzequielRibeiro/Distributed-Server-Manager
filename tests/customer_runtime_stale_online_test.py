"""Regressions: stale Agent observations must never show DayZ online."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
for module in ("dashboard", "database", "core"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / module))
from runtime_instance_projection import project_runtime_state

class StaleOnlineTest(unittest.TestCase):
    def project(self, timestamp):
        return project_runtime_state(
            record={"agent_id": "agent-horizon"},
            runtime_health={"observed_state": "running", "health": "healthy",
                            "reported_at": timestamp},
            agent_health="online", fallback_state="running", fallback_health="healthy")
    def test_stale_running_not_online(self):
        r=self.project((datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat())
        self.assertEqual(r["state"],"unknown")
        self.assertEqual(r["source"],"agent-unavailable")
    def test_fresh_running_still_online(self):
        r=self.project(datetime.now(timezone.utc).isoformat())
        self.assertEqual(r["state"],"online")
    def test_missing_timestamp_not_online(self):
        self.assertEqual(self.project(None)["state"],"unknown")
    def test_failed_reconciliation_cannot_claim_online(self):
        r=project_runtime_state(
            record={"agent_id": "agent-horizon"},
            runtime_health={"observed_state": "running", "health": "degraded",
                            "reconcile_status": "retry_wait",
                            "reported_at": datetime.now(timezone.utc).isoformat()},
            agent_health="online", fallback_state="running", fallback_health="healthy")
        self.assertEqual(r["state"], "unknown")
    def test_future_timestamp_not_online(self):
        r=self.project((datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat())
        self.assertEqual(r["state"],"unknown")
if __name__=="__main__":
    unittest.main()
