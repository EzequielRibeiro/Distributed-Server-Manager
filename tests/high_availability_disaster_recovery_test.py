import tempfile
import unittest
from pathlib import Path

from core.ha_dr import HACluster, HAClusterMember, next_fencing_epoch, quorum_satisfied, select_failover_candidate
from database.backend import DatabaseConfig
from database.backends.sqlite_backend import SQLiteBackend
from database.ha_dr_repository import HADisasterRecoveryRepository


class HADisasterRecoveryContractTests(unittest.TestCase):
    def test_cluster_validates_rpo_rto_and_quorum(self):
        value = HACluster("ha-sp", "SP HA", mode="automatic", rpo_seconds=60, rto_seconds=180, quorum_size=2).normalized()
        self.assertEqual(value["mode"], "automatic")
        self.assertEqual(value["rpo_seconds"], 60)

    def test_candidate_prefers_healthy_then_priority(self):
        members = [
            {"cluster_id":"ha","controller_id":"a","role":"standby","state":"degraded","priority":1},
            {"cluster_id":"ha","controller_id":"b","role":"standby","state":"healthy","priority":20},
            {"cluster_id":"ha","controller_id":"c","role":"standby","state":"healthy","priority":10},
        ]
        self.assertEqual(select_failover_candidate(members)["controller_id"], "c")

    def test_quorum_counts_primary_standby_and_witness(self):
        members = [
            {"role":"primary","state":"offline"},
            {"role":"standby","state":"healthy"},
            {"role":"witness","state":"healthy"},
        ]
        self.assertTrue(quorum_satisfied(members, 2))
        self.assertFalse(quorum_satisfied(members, 3))

    def test_fencing_epoch_is_monotonic(self):
        self.assertEqual(next_fencing_epoch(0), 1)
        self.assertEqual(next_fencing_epoch(41), 42)

    def test_repository_creates_failover_with_new_fencing_epoch(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "capivara.db"
            backend = SQLiteBackend(DatabaseConfig(driver="sqlite", database=str(db)))
            repo = HADisasterRecoveryRepository(backend)
            repo.initialize()
            repo.put_cluster({"cluster_id":"ha-sp","name":"SP HA","mode":"automatic","quorum_size":2})
            repo.put_member({"cluster_id":"ha-sp","controller_id":"ctrl-a","role":"primary","state":"offline","priority":10})
            repo.put_member({"cluster_id":"ha-sp","controller_id":"ctrl-b","role":"standby","state":"healthy","priority":10})
            repo.put_member({"cluster_id":"ha-sp","controller_id":"witness","role":"witness","state":"healthy","priority":100})
            operation = repo.request_failover("ha-sp", automatic=True, reason="primary offline")
            self.assertEqual(operation["target_controller_id"], "ctrl-b")
            self.assertEqual(operation["fencing_epoch"], 1)
            self.assertEqual(operation["state"], "requested")


if __name__ == "__main__":
    unittest.main()
